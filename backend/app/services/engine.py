import asyncio
import contextlib
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.db import SessionLocal
from app.exchanges.base import Exchange, Quote
from app.models import (
    CycleStatus,
    Event,
    Order,
    OrderSide,
    OrderStatus,
    PairConfig,
    PairStatus,
    TradeFill,
    TradeCycle,
)
from app.services.accounting import AccountedFill, calculate_profit
from app.services.pricing import (
    balance_level, irb_after_unmatched_fill, quantities, red_line_crossed, target_prices,
)


OPEN_ORDER_STATUSES = {OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED}
logger = logging.getLogger(__name__)


class MarketMakerEngine:
    def __init__(self, exchange: Exchange, settings: Settings) -> None:
        self.exchange = exchange
        self.settings = settings
        self.quotes: dict[str, tuple[Quote, datetime]] = {}
        self._quote_received_monotonic: dict[str, float] = {}
        self.pair_balances: dict[str, tuple[Decimal, Decimal, datetime]] = {}
        self._account_balance_cache: tuple[dict[str, Decimal], datetime] | None = None
        self._balance_lock = asyncio.Lock()
        self._runner: asyncio.Task | None = None
        self._stream: asyncio.Task | None = None
        self._symbols: set[str] = set()
        self._stream_restart_requested = False
        self._stale_quote_symbols: set[str] = set()
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self._runner = asyncio.create_task(self._run(), name="market-maker-engine")

    async def stop(self) -> None:
        self._stopping = True
        for task in (self._runner, self._stream):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await self.exchange.close()

    async def _on_quote(self, quote: Quote) -> None:
        self.quotes[quote.symbol] = (quote, datetime.now(timezone.utc))
        self._quote_received_monotonic[quote.symbol] = time.monotonic()
        if quote.symbol in self._stale_quote_symbols:
            self._stale_quote_symbols.remove(quote.symbol)
            logger.info("Fresh quote recovered for %s", quote.symbol)

    def _quote_is_stale(self, symbol: str, quoted_at: datetime) -> bool:
        received_at = self._quote_received_monotonic.get(symbol)
        if received_at is not None:
            return time.monotonic() - received_at > self.settings.quote_stale_seconds
        return (datetime.now(timezone.utc) - quoted_at).total_seconds() > self.settings.quote_stale_seconds

    async def ensure_pair_runtime(self, pair: PairConfig) -> None:
        """Populate current quote and balances even while a pair is stopped."""
        quote_item = self.quotes.get(pair.symbol)
        if not quote_item or self._quote_is_stale(pair.symbol, quote_item[1]):
            quote = await self.exchange.book_quote(pair.symbol)
            await self._on_quote(quote)

        now = datetime.now(timezone.utc)
        balance_item = self.pair_balances.get(pair.symbol)
        if not balance_item or (now - balance_item[2]).total_seconds() > self.settings.balance_refresh_seconds:
            balances, balances_at = await self._account_balances()
            self.pair_balances[pair.symbol] = (
                balances.get(pair.base_asset, Decimal("0")),
                balances.get(pair.quote_asset, Decimal("0")),
                balances_at,
            )

    async def _account_balances(self) -> tuple[dict[str, Decimal], datetime]:
        now = datetime.now(timezone.utc)
        cached = self._account_balance_cache
        if cached and (now - cached[1]).total_seconds() < self.settings.balance_refresh_seconds:
            return cached
        async with self._balance_lock:
            cached = self._account_balance_cache
            now = datetime.now(timezone.utc)
            if cached and (now - cached[1]).total_seconds() < self.settings.balance_refresh_seconds:
                return cached
            balances = await self.exchange.balances()
            self._account_balance_cache = (balances, now)
            return balances, now

    async def _refresh_stream(self, symbols: set[str], force: bool = False) -> None:
        if not force and symbols == self._symbols and self._stream and not self._stream.done():
            return
        if self._stream:
            self._stream.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream
        if force:
            # Do not repeatedly classify the same cached quote as stale while
            # the replacement stream is still connecting.
            for symbol in self._stale_quote_symbols:
                self.quotes.pop(symbol, None)
                self._quote_received_monotonic.pop(symbol, None)
        self._symbols = symbols
        if symbols:
            self._stream = asyncio.create_task(
                self.exchange.stream_quotes(symbols, self._on_quote), name="mexc-quotes"
            )

    async def _run(self) -> None:
        while not self._stopping:
            try:
                async with SessionLocal() as session:
                    pairs = list((await session.scalars(select(PairConfig).where(PairConfig.enabled.is_(True)))).all())
                force_stream_restart = self._stream_restart_requested
                self._stream_restart_requested = False
                await self._refresh_stream({pair.symbol for pair in pairs}, force=force_stream_restart)
                await asyncio.gather(*(self._process_safe(pair.id) for pair in pairs))
            except asyncio.CancelledError:
                raise
            except Exception:
                # A top-level failure must not permanently kill the supervisor.
                pass
            await asyncio.sleep(self.settings.engine_tick_seconds)

    async def _process_safe(self, pair_id: uuid.UUID) -> None:
        lock = self._locks.setdefault(pair_id, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            try:
                await self._process(pair_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                async with SessionLocal() as session:
                    pair = await session.get(PairConfig, pair_id)
                    if pair:
                        pair.status = PairStatus.ERROR
                        pair.last_error = str(exc)[:1000]
                        session.add(Event(pair_id=pair.id, level="error", kind="engine_error", message=pair.last_error))
                        await session.commit()

    async def _process(self, pair_id: uuid.UUID) -> None:
        async with SessionLocal() as session:
            pair = await session.get(PairConfig, pair_id)
            if not pair or not pair.enabled:
                return
            now = datetime.now(timezone.utc)
            cycle = await session.scalar(
                select(TradeCycle)
                .where(TradeCycle.pair_id == pair.id, TradeCycle.status == CycleStatus.OPEN)
                .options(selectinload(TradeCycle.orders).selectinload(Order.fills))
                .order_by(TradeCycle.opened_at.desc())
            )

            balances, balances_at = await self._account_balances()
            if balances:
                base_free = balances.get(pair.base_asset, Decimal("0"))
                quote_free = balances.get(pair.quote_asset, Decimal("0"))
                self.pair_balances[pair.symbol] = (base_free, quote_free, balances_at)
                if await self._apply_balance_controls(session, pair, cycle, base_free, quote_free):
                    await session.commit()
                    return

            if pair.paused_until:
                paused_until = pair.paused_until
                if paused_until.tzinfo is None:
                    paused_until = paused_until.replace(tzinfo=timezone.utc)
                if paused_until > now:
                    pair.status = PairStatus.PAUSED
                    await session.commit()
                    return
                pair.paused_until = None
                pair.status = PairStatus.RUNNING

            quote_item = self.quotes.get(pair.symbol)
            if not quote_item:
                return
            quote, quoted_at = quote_item
            if self._quote_is_stale(pair.symbol, quoted_at):
                self._stream_restart_requested = True
                if pair.symbol not in self._stale_quote_symbols:
                    self._stale_quote_symbols.add(pair.symbol)
                    logger.warning("Quote for %s is stale; restarting the quote stream", pair.symbol)
                # A stale quote is a temporary data condition, not a trading
                # failure. Keep existing orders untouched and wait for a fresh
                # book update before making any decision.
                if pair.status == PairStatus.ERROR and pair.last_error and pair.last_error.startswith("stale quote"):
                    pair.status = PairStatus.RUNNING
                    pair.last_error = None
                    await session.commit()
                return

            if cycle is None:
                await self._open_cycle(session, pair, quote)
            else:
                await self._update_cycle(session, pair, cycle, quote)
            pair.last_error = None
            if pair.status == PairStatus.ERROR:
                pair.status = PairStatus.RUNNING
            await session.commit()

    async def _open_cycle(self, session, pair: PairConfig, quote: Quote) -> None:
        prices = target_prices(
            quote.bid, quote.ask, pair.spread_pct, pair.order_offset_pct, pair.irb, pair.price_precision
        )
        buy_qty, sell_qty = quantities(pair.lot_quote, prices, pair.quantity_precision)
        if buy_qty <= 0 or sell_qty <= 0:
            raise RuntimeError("lot is below quantity precision")
        if not self.settings.dry_run:
            balance_item = self.pair_balances.get(pair.symbol)
            if not balance_item:
                raise RuntimeError(f"balances unavailable for {pair.symbol}")
            base_free, quote_free, _ = balance_item
            if quote_free < pair.lot_quote:
                raise RuntimeError(
                    f"insufficient {pair.quote_asset}: need {pair.lot_quote}, available {quote_free}"
                )
            if base_free < sell_qty:
                raise RuntimeError(
                    f"insufficient {pair.base_asset}: need {sell_qty}, available {base_free}"
                )
        cycle = TradeCycle(pair_id=pair.id, reference_bid=quote.bid, reference_ask=quote.ask)
        session.add(cycle)
        await session.flush()
        placed: list[tuple[OrderSide, object, Decimal, Decimal, str]] = []
        try:
            for side, qty, price in (
                (OrderSide.BUY, buy_qty, prices.buy), (OrderSide.SELL, sell_qty, prices.sell)
            ):
                client_id = f"mm-{cycle.id.hex[:16]}-{side.value.lower()}"
                result = await self.exchange.place_limit(pair.symbol, side, qty, price, client_id)
                placed.append((side, result, qty, price, client_id))
        except Exception:
            for _, result, _, _, _ in placed:
                with contextlib.suppress(Exception):
                    await self.exchange.cancel(pair.symbol, result.order_id)
            raise
        for side, result, qty, price, client_id in placed:
            session.add(Order(cycle_id=cycle.id, exchange_order_id=result.order_id,
                              client_order_id=client_id, side=side, status=result.status,
                              price=price, quantity=qty, executed_quantity=result.executed_quantity))
        session.add(Event(pair_id=pair.id, kind="orders_placed",
                          message=f"BUY {buy_qty} @ {prices.buy}; SELL {sell_qty} @ {prices.sell}"))

    async def _update_cycle(self, session, pair: PairConfig, cycle: TradeCycle, quote: Quote) -> None:
        for order in cycle.orders:
            if order.status in OPEN_ORDER_STATUSES:
                result = await self.exchange.order(pair.symbol, order.exchange_order_id)
                order.status = result.status
                order.executed_quantity = result.executed_quantity

        filled = [order for order in cycle.orders if order.status == OrderStatus.FILLED]
        open_orders = [order for order in cycle.orders if order.status in OPEN_ORDER_STATUSES]
        mark_price = (quote.bid + quote.ask) / Decimal("2")
        for order in filled:
            await self._sync_order_fills(pair, order, mark_price)
        if len(filled) == 2:
            if not await self._settle_cycle(pair, cycle, filled, mark_price):
                return
            cycle.status = CycleStatus.PROFITABLE
            cycle.closed_at = datetime.now(timezone.utc)
            session.add(Event(pair_id=pair.id, kind="profitable_cycle",
                              message=(f"Both orders filled; gross={cycle.gross_profit_quote} "
                                       f"fee={cycle.commission_quote} net={cycle.net_profit_quote} "
                                       f"{pair.quote_asset}")))
            return

        canceled = [order for order in cycle.orders if order.status in {OrderStatus.CANCELED, OrderStatus.EXPIRED}]
        if len(filled) == 1 and (open_orders or canceled):
            winner = filled[0]
            crossed = bool(canceled) or red_line_crossed(
                winner.side.value, winner.price, quote.bid, quote.ask, pair.red_line_pct
            )
            if crossed:
                for order in open_orders:
                    result = await self.exchange.cancel(pair.symbol, order.exchange_order_id)
                    order.status = result.status
                    order.executed_quantity = result.executed_quantity
                if not await self._settle_cycle(pair, cycle, filled, mark_price):
                    return
                previous_irb = pair.irb
                pair.irb = irb_after_unmatched_fill(pair.irb, winner.side.value)
                cycle.status = CycleStatus.RED_LINE
                cycle.closed_at = datetime.now(timezone.utc)
                pair.paused_until = datetime.now(timezone.utc) + timedelta(minutes=pair.pause_minutes)
                pair.status = PairStatus.PAUSED
                session.add(Event(pair_id=pair.id, level="warning", kind="red_line",
                                  message=(f"{winner.side.value} filled; IRB {previous_irb} -> {pair.irb}; "
                                           f"gross={cycle.gross_profit_quote} fee={cycle.commission_quote} "
                                           f"net={cycle.net_profit_quote} {pair.quote_asset}")))

    async def _settle_cycle(
        self,
        pair: PairConfig,
        cycle: TradeCycle,
        filled_orders: list[Order],
        mark_price: Decimal,
    ) -> bool:
        accounted: list[AccountedFill] = []
        for order in filled_orders:
            if not order.fills and not await self._sync_order_fills(pair, order, mark_price):
                # MEXC order status can arrive slightly before myTrades.
                return False
            accounted.extend(
                AccountedFill(order.side, fill.quantity, fill.quote_quantity, fill.commission_quote)
                for fill in order.fills
            )

        result = calculate_profit(accounted, mark_price)
        cycle.gross_profit_quote = result.gross_profit
        cycle.commission_quote = result.commission
        cycle.net_profit_quote = result.net_profit
        cycle.mark_price = mark_price
        return True

    async def _sync_order_fills(
        self, pair: PairConfig, order: Order, mark_price: Decimal
    ) -> bool:
        if order.fills:
            return True
        exchange_fills = await self.exchange.fills(pair.symbol, order.exchange_order_id)
        for fill in exchange_fills:
            commission_quote = await self._commission_in_quote(
                pair, fill.commission, fill.commission_asset, mark_price
            )
            order.fills.append(TradeFill(
                order_id=order.id, exchange_trade_id=fill.trade_id, price=fill.price,
                quantity=fill.quantity, quote_quantity=fill.quote_quantity,
                quote_quantity_usdt=await self._amount_in_usdt(
                    pair.quote_asset, fill.quote_quantity
                ),
                commission=fill.commission,
                commission_asset=fill.commission_asset or pair.quote_asset,
                commission_quote=commission_quote,
            ))
        return bool(exchange_fills)

    async def _amount_in_usdt(self, asset: str, amount: Decimal) -> Decimal:
        """Convert an execution value to USDT at settlement time."""
        asset = asset.upper()
        if asset == "USDT":
            return amount
        try:
            conversion = await self.exchange.book_quote(f"{asset}USDT")
            return amount * (conversion.bid + conversion.ask) / Decimal("2")
        except Exception:
            conversion = await self.exchange.book_quote(f"USDT{asset}")
            return amount / ((conversion.bid + conversion.ask) / Decimal("2"))

    async def _commission_in_quote(
        self,
        pair: PairConfig,
        amount: Decimal,
        asset: str,
        mark_price: Decimal,
    ) -> Decimal:
        if amount == 0:
            return Decimal("0")
        asset = asset.upper()
        if not asset or asset == "__QUOTE__" or asset == pair.quote_asset:
            return amount
        if asset == pair.base_asset:
            return amount * mark_price
        try:
            conversion = await self.exchange.book_quote(f"{asset}{pair.quote_asset}")
            return amount * (conversion.bid + conversion.ask) / Decimal("2")
        except Exception:
            conversion = await self.exchange.book_quote(f"{pair.quote_asset}{asset}")
            return amount / ((conversion.bid + conversion.ask) / Decimal("2"))

    async def _apply_balance_controls(
        self,
        session,
        pair: PairConfig,
        cycle: TradeCycle | None,
        base_free: Decimal,
        quote_free: Decimal,
    ) -> bool:
        base_level = balance_level(base_free, pair.base_balance_trigger, pair.base_balance_limit)
        quote_level = balance_level(quote_free, pair.quote_balance_trigger, pair.quote_balance_limit)

        limits = []
        if base_level == "limit":
            limits.append(f"{pair.base_asset}={base_free} <= {pair.base_balance_limit}")
        if quote_level == "limit":
            limits.append(f"{pair.quote_asset}={quote_free} <= {pair.quote_balance_limit}")
        if limits:
            await self._cancel_cycle_orders(pair, cycle)
            pair.enabled = False
            pair.status = PairStatus.LIMIT_REACHED
            session.add(Event(
                pair_id=pair.id,
                level="critical",
                kind="balance_limit",
                message="Trading stopped: " + "; ".join(limits),
            ))
            return True

        for asset, value, trigger, level, alert_attr in (
            (pair.base_asset, base_free, pair.base_balance_trigger, base_level, "base_balance_alerted"),
            (pair.quote_asset, quote_free, pair.quote_balance_trigger, quote_level, "quote_balance_alerted"),
        ):
            alerted = getattr(pair, alert_attr)
            if level == "trigger" and not alerted:
                setattr(pair, alert_attr, True)
                session.add(Event(
                    pair_id=pair.id,
                    level="warning",
                    kind="balance_trigger",
                    message=f"Manual rebalance requested: {asset}={value} <= {trigger}",
                ))
            elif level == "ok" and alerted:
                setattr(pair, alert_attr, False)
                session.add(Event(
                    pair_id=pair.id,
                    kind="balance_recovered",
                    message=f"{asset} balance recovered: {value} > {trigger}",
                ))
        return False

    async def _cancel_cycle_orders(self, pair: PairConfig, cycle: TradeCycle | None) -> None:
        if not cycle:
            return
        for order in cycle.orders:
            if order.status in OPEN_ORDER_STATUSES:
                result = await self.exchange.cancel(pair.symbol, order.exchange_order_id)
                order.status = result.status
                order.executed_quantity = result.executed_quantity
        cycle.status = CycleStatus.CANCELED
        cycle.closed_at = datetime.now(timezone.utc)

    async def cancel_pair_orders(self, pair_id: uuid.UUID) -> None:
        lock = self._locks.setdefault(pair_id, asyncio.Lock())
        async with lock, SessionLocal() as session:
            pair = await session.get(PairConfig, pair_id)
            if not pair:
                return
            cycle = await session.scalar(
                select(TradeCycle).where(TradeCycle.pair_id == pair.id, TradeCycle.status == CycleStatus.OPEN)
                .options(selectinload(TradeCycle.orders).selectinload(Order.fills))
            )
            if cycle:
                await self._cancel_cycle_orders(pair, cycle)
            session.add(Event(pair_id=pair.id, kind="manual_stop", message="Trading stopped; open orders canceled"))
            await session.commit()

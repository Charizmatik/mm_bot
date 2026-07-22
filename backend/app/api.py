import uuid
import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_session
from app.models import CycleStatus, Event, Order, OrderStatus, PairConfig, PairStatus, TradeCycle
from app.schemas import (
    EventRead, FillRead, Health, ManualIrb, OrderRead, PairCreate, PairRead, PairRuntime, PairUpdate,
    PairStatistics, ProfitBucket, Statistics,
    SymbolRead,
)

router = APIRouter(prefix="/api")
_symbol_cache: tuple[list, datetime] | None = None
_symbol_lock = asyncio.Lock()


def reported_cycle_profit(cycle: TradeCycle, paper_profit: bool) -> tuple[Decimal, Decimal, Decimal]:
    """Return the P&L shown in statistics for a completed cycle.

    Paper-profit mode treats a red-line inventory move as unrealized: the
    cycle and its volume remain visible, but only its mark-to-market result is
    excluded.  Executed-order commissions are real costs and must still reduce
    reported P&L.
    """
    if paper_profit and cycle.status == CycleStatus.RED_LINE:
        zero = Decimal("0")
        return zero, cycle.commission_quote, -cycle.commission_quote
    return cycle.gross_profit_quote, cycle.commission_quote, cycle.net_profit_quote


def normalize_symbol(value: str) -> str:
    return value.upper().replace("_", "").replace("/", "").replace("-", "")


async def _exchange_symbols(request: Request) -> list:
    global _symbol_cache
    now = datetime.now(timezone.utc)
    if _symbol_cache and now - _symbol_cache[1] < timedelta(minutes=10):
        return _symbol_cache[0]
    async with _symbol_lock:
        now = datetime.now(timezone.utc)
        if _symbol_cache and now - _symbol_cache[1] < timedelta(minutes=10):
            return _symbol_cache[0]
        symbols = await request.app.state.engine.exchange.symbols()
        _symbol_cache = (symbols, now)
        return symbols


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health(status="ok", dry_run=get_settings().dry_run)


@router.get("/symbols", response_model=list[SymbolRead])
async def list_symbols(request: Request, q: str = "", limit: int = 30) -> list[SymbolRead]:
    query = normalize_symbol(q)
    symbols = await _exchange_symbols(request)
    if query:
        starts = [item for item in symbols if item.symbol.startswith(query)]
        contains = [item for item in symbols if query in item.symbol and not item.symbol.startswith(query)]
        quote_rank = {"USDT": 0, "USDC": 1, "BTC": 2, "ETH": 3}
        starts.sort(key=lambda item: (
            item.base_asset != query,
            quote_rank.get(item.quote_asset, 10),
            item.symbol,
        ))
        contains.sort(key=lambda item: item.symbol)
        symbols = starts + contains
    else:
        preferred = {"BTCUSDT": 0, "ETHUSDT": 1, "SOLUSDT": 2, "XRPUSDT": 3}
        symbols = sorted(symbols, key=lambda item: (preferred.get(item.symbol, 100), item.symbol))
    return [SymbolRead(**item.__dict__) for item in symbols[:min(max(limit, 1), 100)]]


@router.get("/pairs", response_model=list[PairRuntime])
async def list_pairs(request: Request, session: AsyncSession = Depends(get_session)) -> list[PairRuntime]:
    pairs = list((await session.scalars(select(PairConfig).order_by(PairConfig.created_at))).all())
    result = []
    for pair in pairs:
        with contextlib.suppress(Exception):
            await request.app.state.engine.ensure_pair_runtime(pair)
        quote_item = request.app.state.engine.quotes.get(pair.symbol)
        balance_item = request.app.state.engine.pair_balances.get(pair.symbol)
        open_count = await session.scalar(
            select(func.count(Order.id)).join(TradeCycle).where(
                TradeCycle.pair_id == pair.id,
                Order.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED]),
            )
        )
        quote, quoted_at = quote_item if quote_item else (None, None)
        base_free, quote_free, balance_updated_at = balance_item if balance_item else (None, None, None)
        result.append(PairRuntime(pair=PairRead.model_validate(pair), bid=quote.bid if quote else None,
                                  ask=quote.ask if quote else None, quote_updated_at=quoted_at,
                                  base_free=base_free, quote_free=quote_free,
                                  balance_updated_at=balance_updated_at,
                                  open_orders=open_count or 0))
    return result


@router.post("/pairs", response_model=PairRead, status_code=status.HTTP_201_CREATED)
async def create_pair(payload: PairCreate, session: AsyncSession = Depends(get_session)) -> PairConfig:
    symbol = normalize_symbol(payload.symbol)
    if await session.scalar(select(PairConfig).where(PairConfig.symbol == symbol)):
        raise HTTPException(409, "Pair already exists")
    values = payload.model_dump()
    values["symbol"] = symbol
    values["base_asset"] = payload.base_asset.upper()
    values["quote_asset"] = payload.quote_asset.upper()
    pair = PairConfig(**values)
    session.add(pair)
    await session.commit()
    await session.refresh(pair)
    return pair


@router.put("/pairs/{pair_id}", response_model=PairRead)
async def update_pair(pair_id: uuid.UUID, payload: PairUpdate, session: AsyncSession = Depends(get_session)) -> PairConfig:
    pair = await session.get(PairConfig, pair_id)
    if not pair:
        raise HTTPException(404, "Pair not found")
    if pair.enabled:
        raise HTTPException(409, "Stop the pair before editing")
    symbol = normalize_symbol(payload.symbol)
    duplicate = await session.scalar(
        select(PairConfig).where(PairConfig.symbol == symbol, PairConfig.id != pair.id)
    )
    if duplicate:
        raise HTTPException(409, "Pair already exists")
    values = payload.model_dump()
    values.update(symbol=symbol, base_asset=payload.base_asset.upper(), quote_asset=payload.quote_asset.upper())
    for key, value in values.items():
        setattr(pair, key, value)
    pair.base_balance_alerted = False
    pair.quote_balance_alerted = False
    pair.last_error = None
    session.add(Event(pair_id=pair.id, kind="configuration_updated",
                      message="All trading pair options updated"))
    await session.commit()
    await session.refresh(pair)
    return pair


@router.post("/pairs/{pair_id}/start", response_model=PairRead)
async def start_pair(pair_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> PairConfig:
    pair = await session.get(PairConfig, pair_id)
    if not pair:
        raise HTTPException(404, "Pair not found")
    pair.enabled = True
    pair.status = PairStatus.RUNNING
    pair.last_error = None
    session.add(Event(pair_id=pair.id, kind="manual_start", message="Trading started"))
    await session.commit()
    await session.refresh(pair)
    return pair


@router.post("/pairs/{pair_id}/stop", response_model=PairRead)
async def stop_pair(pair_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> PairConfig:
    pair = await session.get(PairConfig, pair_id)
    if not pair:
        raise HTTPException(404, "Pair not found")
    pair.enabled = False
    pair.status = PairStatus.STOPPED
    session.add(Event(
        pair_id=pair.id,
        kind="manual_stop",
        message="Trading stopped; existing orders will be checked on restart",
    ))
    await session.commit()
    await session.refresh(pair)
    return pair


@router.post("/pairs/{pair_id}/irb", response_model=PairRead)
async def set_irb(pair_id: uuid.UUID, payload: ManualIrb, session: AsyncSession = Depends(get_session)) -> PairConfig:
    pair = await session.get(PairConfig, pair_id)
    if not pair:
        raise HTTPException(404, "Pair not found")
    if pair.enabled:
        raise HTTPException(409, "Stop the pair before manual rebalance")
    previous = pair.irb
    pair.irb = payload.value
    pair.last_error = None
    session.add(Event(pair_id=pair.id, kind="manual_rebalance",
                      message=f"IRB {previous} -> {payload.value}. Note: {payload.note}"))
    await session.commit()
    await session.refresh(pair)
    return pair


@router.get("/events", response_model=list[EventRead])
async def list_events(pair_id: uuid.UUID | None = None, limit: int = 100,
                      session: AsyncSession = Depends(get_session)) -> list[Event]:
    query = select(Event).order_by(Event.created_at.desc()).limit(min(max(limit, 1), 500))
    if pair_id:
        query = query.where(Event.pair_id == pair_id)
    return list((await session.scalars(query)).all())


@router.get("/orders", response_model=list[OrderRead])
async def list_orders(
    pair_id: uuid.UUID | None = None,
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
) -> list[OrderRead]:
    query = (
        select(Order, TradeCycle, PairConfig)
        .join(TradeCycle, Order.cycle_id == TradeCycle.id)
        .join(PairConfig, TradeCycle.pair_id == PairConfig.id)
        .options(selectinload(Order.fills))
        .order_by(Order.created_at.desc())
        .limit(min(max(limit, 1), 500))
    )
    if pair_id:
        query = query.where(TradeCycle.pair_id == pair_id)

    result = []
    for order, cycle, pair in (await session.execute(query)).all():
        execution_pct = (
            order.executed_quantity * Decimal("100") / order.quantity
            if order.quantity else Decimal("0")
        )
        result.append(OrderRead(
            id=order.id, cycle_id=cycle.id, pair_id=pair.id, symbol=pair.symbol,
            base_asset=pair.base_asset, quote_asset=pair.quote_asset,
            cycle_status=cycle.status, exchange_order_id=order.exchange_order_id,
            client_order_id=order.client_order_id, side=order.side, status=order.status,
            price=order.price, quantity=order.quantity,
            executed_quantity=order.executed_quantity,
            quote_value=order.price * order.quantity, execution_pct=execution_pct,
            created_at=order.created_at, updated_at=order.updated_at,
            fills=[FillRead.model_validate(fill) for fill in order.fills],
        ))
    return result


@router.get("/statistics", response_model=Statistics)
async def statistics(
    paper_profit: bool = False,
    session: AsyncSession = Depends(get_session),
) -> Statistics:
    rows = (
        await session.execute(
            select(TradeCycle, PairConfig)
            .join(PairConfig, TradeCycle.pair_id == PairConfig.id)
            .options(selectinload(TradeCycle.orders).selectinload(Order.fills))
            .where(TradeCycle.status.in_([CycleStatus.PROFITABLE, CycleStatus.RED_LINE]))
        )
    ).all()

    quote_totals: dict[str, dict[str, Decimal]] = {}
    pair_totals: dict[uuid.UUID, dict] = {}
    successful = unsuccessful = 0
    for cycle, pair in rows:
        is_success = cycle.status == CycleStatus.PROFITABLE
        successful += int(is_success)
        unsuccessful += int(not is_success)
        reported_gross, reported_commission, reported_net = reported_cycle_profit(cycle, paper_profit)
        quote = quote_totals.setdefault(
            pair.quote_asset,
            {"volume": Decimal("0"), "volume_usdt": Decimal("0"),
             "gross": Decimal("0"), "commission": Decimal("0"), "net": Decimal("0")},
        )
        cycle_volume = sum(
            (fill.quote_quantity for order in cycle.orders for fill in order.fills), Decimal("0")
        )
        cycle_volume_usdt = sum(
            (fill.quote_quantity_usdt or Decimal("0")
             for order in cycle.orders for fill in order.fills), Decimal("0")
        )
        quote["volume"] += cycle_volume
        quote["volume_usdt"] += cycle_volume_usdt
        quote["gross"] += reported_gross
        quote["commission"] += reported_commission
        quote["net"] += reported_net

        item = pair_totals.setdefault(pair.id, {
            "symbol": pair.symbol, "quote_asset": pair.quote_asset, "successful": 0, "unsuccessful": 0,
            "volume": Decimal("0"), "volume_usdt": Decimal("0"),
            "gross": Decimal("0"), "commission": Decimal("0"), "net": Decimal("0"),
        })
        item["successful" if is_success else "unsuccessful"] += 1
        item["volume"] += cycle_volume
        item["volume_usdt"] += cycle_volume_usdt
        item["gross"] += reported_gross
        item["commission"] += reported_commission
        item["net"] += reported_net

    total = successful + unsuccessful
    rate = Decimal(successful * 100) / Decimal(total) if total else Decimal("0")
    return Statistics(
        successful_trades=successful,
        unsuccessful_trades=unsuccessful,
        total_trades=total,
        success_rate_pct=rate,
        by_quote_asset=[
            ProfitBucket(quote_asset=asset, trading_volume=value["volume"],
                         trading_volume_usdt=value["volume_usdt"], gross_profit=value["gross"],
                         commission=value["commission"], net_profit=value["net"])
            for asset, value in sorted(quote_totals.items())
        ],
        pairs=[
            PairStatistics(
                pair_id=pair_id, symbol=value["symbol"], quote_asset=value["quote_asset"],
                successful_trades=value["successful"], unsuccessful_trades=value["unsuccessful"],
                total_trades=value["successful"] + value["unsuccessful"],
                success_rate_pct=(Decimal(value["successful"] * 100) /
                                  Decimal(value["successful"] + value["unsuccessful"])),
                trading_volume=value["volume"], trading_volume_usdt=value["volume_usdt"],
                gross_profit=value["gross"], commission=value["commission"], net_profit=value["net"],
            )
            for pair_id, value in pair_totals.items()
        ],
    )

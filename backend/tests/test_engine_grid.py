import uuid
from decimal import Decimal

import pytest

from app.config import Settings
from app.exchanges.base import ExchangeOrder, Quote
from app.models import (
    CycleStatus, Order, OrderSide, OrderStatus, PairConfig, TradeCycle,
)
from app.services.engine import MarketMakerEngine


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if isinstance(value, TradeCycle) and value.id is None:
                value.id = uuid.uuid4()


class FakeExchange:
    def __init__(self) -> None:
        self.placed: list[tuple[OrderSide, Decimal, Decimal]] = []

    async def place_limit(self, symbol, side, quantity, price, client_order_id):
        self.placed.append((side, quantity, price))
        return ExchangeOrder(
            order_id=f"order-{len(self.placed)}",
            client_order_id=client_order_id,
            status=OrderStatus.NEW,
            executed_quantity=Decimal("0"),
        )

    async def cancel(self, symbol, order_id):
        raise AssertionError("cancel was not expected")


def pair(order_pair_count: int) -> PairConfig:
    return PairConfig(
        id=uuid.uuid4(),
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        lot_quote=Decimal("100"),
        spread_pct=Decimal("0.15"),
        base_balance_trigger=Decimal("1"),
        base_balance_limit=Decimal("0.5"),
        quote_balance_trigger=Decimal("500"),
        quote_balance_limit=Decimal("200"),
        order_offset_pct=Decimal("0.005"),
        red_line_pct=Decimal("1"),
        pause_minutes=1,
        price_precision=3,
        quantity_precision=6,
        order_pair_count=order_pair_count,
    )


def open_cycle(slot: int, buy: str, sell: str, *, reference: str = "100") -> TradeCycle:
    cycle = TradeCycle(
        id=uuid.uuid4(),
        pair_id=uuid.uuid4(),
        status=CycleStatus.OPEN,
        reference_bid=Decimal(reference),
        reference_ask=Decimal(reference),
        grid_slot=slot,
    )
    cycle.orders = [
        Order(
            exchange_order_id=f"buy-{slot}",
            client_order_id=f"buy-client-{slot}",
            side=OrderSide.BUY,
            status=OrderStatus.NEW,
            price=Decimal(buy),
            quantity=Decimal("1"),
        ),
        Order(
            exchange_order_id=f"sell-{slot}",
            client_order_id=f"sell-client-{slot}",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            price=Decimal(sell),
            quantity=Decimal("1"),
        ),
    ]
    return cycle


@pytest.mark.asyncio
async def test_filled_outer_sell_adds_exact_adjacent_pair() -> None:
    exchange = FakeExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=True))  # type: ignore[arg-type]
    config = pair(2)
    cycle = open_cycle(0, "99.850", "100.000")
    session = FakeSession()

    created = await engine._maybe_expand_grid(
        session,
        config,
        cycle,
        cycle.orders[1],
        [cycle],
        Quote(config.symbol, Decimal("100.001"), Decimal("100.002")),
    )

    assert created
    assert [item[2] for item in exchange.placed] == [Decimal("100.001"), Decimal("100.151")]


@pytest.mark.asyncio
async def test_late_first_addition_bootstraps_at_current_market_with_gap() -> None:
    exchange = FakeExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=True))  # type: ignore[arg-type]
    config = pair(2)
    cycle = open_cycle(0, "99.850", "100.000")
    session = FakeSession()

    created = await engine._maybe_expand_grid(
        session,
        config,
        cycle,
        cycle.orders[1],
        [cycle],
        Quote(config.symbol, Decimal("101"), Decimal("101.01")),
    )

    assert created
    assert exchange.placed[0][2] > Decimal("100")
    assert exchange.placed[0][2] < Decimal("101.01")
    assert exchange.placed[1][2] > Decimal("101")


@pytest.mark.asyncio
async def test_decrease_marks_farthest_grid_pair_for_retirement() -> None:
    engine = MarketMakerEngine(FakeExchange(), Settings(dry_run=True))  # type: ignore[arg-type]
    config = pair(2)
    cycles = [
        open_cycle(-1, "98.8", "99.0", reference="99"),
        open_cycle(0, "99.8", "100.2", reference="100"),
        open_cycle(1, "101.0", "101.2", reference="101.1"),
    ]

    await engine._reconcile_grid(
        FakeSession(),
        config,
        cycles,
        Quote(config.symbol, Decimal("99.9"), Decimal("100.1")),
    )

    assert cycles[2].retiring
    assert not cycles[0].retiring
    assert not cycles[1].retiring

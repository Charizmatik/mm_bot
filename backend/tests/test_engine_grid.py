import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.config import Settings
from app.exchanges.base import AssetBalance, ExchangeOrder, Quote, TransientExchangeError
from app.models import (
    CycleStatus, Event, Order, OrderSide, OrderStatus, PairConfig, PairStatus,
    TradeCycle,
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
        self.account_balances: dict[str, AssetBalance] = {}
        self.balance_calls = 0

    async def balances(self):
        self.balance_calls += 1
        return self.account_balances

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


class SafeCancelExchange(FakeExchange):
    def __init__(self) -> None:
        super().__init__()
        self.canceled: list[tuple[str, str]] = []

    async def cancel(self, symbol, order_id):
        self.canceled.append((symbol, order_id))
        return ExchangeOrder(
            order_id=order_id,
            client_order_id="",
            status=OrderStatus.CANCELED,
            executed_quantity=Decimal("0"),
        )

    async def order(self, symbol, order_id):
        return ExchangeOrder(
            order_id=order_id,
            client_order_id="",
            status=OrderStatus.NEW,
            executed_quantity=Decimal("0"),
        )


class ErrorSession:
    def __init__(self, config: PairConfig) -> None:
        self.config = config
        self.added: list[object] = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, model, value_id):
        if model is PairConfig and value_id == self.config.id:
            return self.config
        return None

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.committed = True


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
    assert [item[2] for item in exchange.placed] == [
        Decimal("100.850"),
        Decimal("101.001"),
    ]


@pytest.mark.asyncio
async def test_closed_historical_slot_does_not_block_grid_expansion() -> None:
    exchange = FakeExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=True))  # type: ignore[arg-type]
    config = pair(2)
    dormant = open_cycle(0, "98.8", "99.0")
    dormant.status = CycleStatus.CANCELED
    live = open_cycle(1, "99.850", "100.000")
    cycles = [dormant, live]

    created = await engine._maybe_expand_grid(
        FakeSession(),
        config,
        live,
        live.orders[1],
        cycles,
        Quote(config.symbol, Decimal("100.001"), Decimal("100.002")),
    )

    assert created
    assert dormant.retiring
    assert cycles[-1].grid_slot == 2
    assert [item[2] for item in exchange.placed] == [
        Decimal("100.001"),
        Decimal("100.151"),
    ]


@pytest.mark.asyncio
async def test_cycle_with_all_orders_canceled_on_exchange_is_closed() -> None:
    exchange = FakeExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=True))  # type: ignore[arg-type]
    config = pair(2)
    cycle = open_cycle(0, "99.850", "100.000")
    for order in cycle.orders:
        order.status = OrderStatus.CANCELED
    session = FakeSession()

    await engine._update_cycle(
        session,
        config,
        cycle,
        [cycle],
        Quote(config.symbol, Decimal("100.001"), Decimal("100.002")),
    )

    assert cycle.status == CycleStatus.CANCELED
    assert cycle.closed_at is not None
    event = next(value for value in session.added if isinstance(value, Event))
    assert event.kind == "orders_canceled"


@pytest.mark.asyncio
async def test_one_canceled_order_cancels_the_remaining_pair_order() -> None:
    exchange = SafeCancelExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=True))  # type: ignore[arg-type]
    config = pair(2)
    cycle = open_cycle(0, "99.850", "100.000")
    buy = next(order for order in cycle.orders if order.side == OrderSide.BUY)
    sell = next(order for order in cycle.orders if order.side == OrderSide.SELL)
    buy.status = OrderStatus.NEW
    sell.status = OrderStatus.CANCELED
    session = FakeSession()

    await engine._update_cycle(
        session,
        config,
        cycle,
        [cycle],
        Quote(config.symbol, Decimal("100.001"), Decimal("100.002")),
    )

    assert exchange.canceled == [(config.symbol, buy.exchange_order_id)]
    assert buy.status == OrderStatus.CANCELED
    assert cycle.status == CycleStatus.CANCELED
    event = next(value for value in session.added if isinstance(value, Event))
    assert event.kind == "orders_canceled"
    assert "remaining order was canceled too" in event.message


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


@pytest.mark.asyncio
async def test_replacement_above_neighbor_uses_minimum_adjacent_gap() -> None:
    exchange = FakeExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=True))  # type: ignore[arg-type]
    config = pair(2)
    config.price_precision = 2
    neighbor = open_cycle(0, "1920.07", "1922.97")
    completed = open_cycle(1, "1923.39", "1926.29")
    completed.status = CycleStatus.PROFITABLE
    cycles = [neighbor, completed]

    await engine._reconcile_grid(
        FakeSession(),
        config,
        cycles,
        Quote(config.symbol, Decimal("1924"), Decimal("1924.01")),
    )

    assert [item[2] for item in exchange.placed] == [
        Decimal("1922.98"),
        Decimal("1925.86"),
    ]


@pytest.mark.asyncio
async def test_replacement_below_neighbor_uses_adjacent_boundary() -> None:
    exchange = FakeExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=True))  # type: ignore[arg-type]
    config = pair(2)
    config.price_precision = 2
    completed = open_cycle(-1, "1917.16", "1920.05")
    completed.status = CycleStatus.PROFITABLE
    neighbor = open_cycle(0, "1920.07", "1922.97")
    cycles = [completed, neighbor]

    await engine._reconcile_grid(
        FakeSession(),
        config,
        cycles,
        Quote(config.symbol, Decimal("1919"), Decimal("1919.01")),
    )

    assert [item[2] for item in exchange.placed] == [
        Decimal("1917.16"),
        Decimal("1920.05"),
    ]


@pytest.mark.asyncio
async def test_adjacent_replacement_uses_smallest_maker_safe_gap() -> None:
    exchange = FakeExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=True))  # type: ignore[arg-type]
    config = pair(2)
    config.price_precision = 2
    neighbor = open_cycle(0, "1920.07", "1922.97")
    completed = open_cycle(1, "1923.39", "1926.29")
    completed.status = CycleStatus.PROFITABLE
    cycles = [neighbor, completed]

    await engine._reconcile_grid(
        FakeSession(),
        config,
        cycles,
        Quote(config.symbol, Decimal("1926"), Decimal("1926.01")),
    )

    assert [item[2] for item in exchange.placed] == [
        Decimal("1923.13"),
        Decimal("1926.01"),
    ]


@pytest.mark.asyncio
async def test_new_cycle_has_initialized_orders_without_async_lazy_load() -> None:
    exchange = FakeExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=True))  # type: ignore[arg-type]
    config = pair(1)
    session = FakeSession()

    cycle = await engine._open_cycle(
        session,
        config,
        Quote(config.symbol, Decimal("99.9"), Decimal("100.1")),
        grid_slot=0,
    )

    assert len(cycle.orders) == 2
    assert {order.side for order in cycle.orders} == {OrderSide.BUY, OrderSide.SELL}


@pytest.mark.asyncio
async def test_live_placement_forces_fresh_free_balance_check() -> None:
    exchange = FakeExchange()
    exchange.account_balances = {
        "BTC": AssetBalance(free=Decimal("0.1"), locked=Decimal("1")),
        "USDT": AssetBalance(free=Decimal("1000")),
    }
    engine = MarketMakerEngine(exchange, Settings(dry_run=False))  # type: ignore[arg-type]
    engine._account_balance_cache = (
        {
            "BTC": AssetBalance(free=Decimal("10")),
            "USDT": AssetBalance(free=Decimal("1000")),
        },
        datetime.now(timezone.utc),
    )

    with pytest.raises(RuntimeError, match="insufficient free BTC"):
        await engine._open_cycle(
            FakeSession(),
            pair(1),
            Quote("BTCUSDT", Decimal("99.9"), Decimal("100.1")),
            grid_slot=0,
        )

    assert exchange.balance_calls == 1
    assert exchange.placed == []


@pytest.mark.asyncio
async def test_locked_inventory_does_not_trigger_balance_limit() -> None:
    exchange = FakeExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=False))  # type: ignore[arg-type]
    config = pair(1)
    config.base_balance_trigger = Decimal("0.8")
    config.base_balance_limit = Decimal("0.5")
    config.enabled = True

    stopped = await engine._apply_balance_controls(
        FakeSession(),
        config,
        [],
        AssetBalance(free=Decimal("0.01"), locked=Decimal("0.99")).total,
        Decimal("1000"),
    )

    assert not stopped
    assert config.enabled


@pytest.mark.asyncio
async def test_engine_error_cancels_uncommitted_orders_and_disables_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = SafeCancelExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=False))  # type: ignore[arg-type]
    config = pair(1)
    config.enabled = True
    session = ErrorSession(config)
    engine._pending_exchange_orders[config.id] = [
        (config.symbol, "uncommitted-buy"),
        (config.symbol, "uncommitted-sell"),
    ]

    async def fail_processing(pair_id):
        raise RuntimeError("database transaction failed")

    engine._process = fail_processing  # type: ignore[method-assign]
    monkeypatch.setattr("app.services.engine.SessionLocal", lambda: session)

    await engine._process_safe(config.id)

    assert exchange.canceled == [
        (config.symbol, "uncommitted-buy"),
        (config.symbol, "uncommitted-sell"),
    ]
    assert not config.enabled
    assert config.status == PairStatus.ERROR
    assert session.committed
    event = next(value for value in session.added if isinstance(value, Event))
    assert "Trading disabled after error" in event.message


@pytest.mark.asyncio
async def test_temporary_exchange_error_keeps_pair_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = SafeCancelExchange()
    engine = MarketMakerEngine(exchange, Settings(dry_run=False))  # type: ignore[arg-type]
    config = pair(1)
    config.enabled = True
    config.status = PairStatus.RUNNING
    session = ErrorSession(config)

    async def fail_processing(pair_id):
        raise TransientExchangeError("MEXC GET /api/v3/order timed out")

    engine._process = fail_processing  # type: ignore[method-assign]
    monkeypatch.setattr("app.services.engine.SessionLocal", lambda: session)

    await engine._process_safe(config.id)

    assert config.enabled
    assert config.status == PairStatus.RUNNING
    assert config.last_error and "timed out" in config.last_error
    assert exchange.canceled == []
    event = next(value for value in session.added if isinstance(value, Event))
    assert event.kind == "exchange_timeout"

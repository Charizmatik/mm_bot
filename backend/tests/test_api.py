import uuid
from decimal import Decimal

import pytest

from app.api import (
    _next_period, _period_start, order_distance_pct, order_distance_values,
    red_line_values, reported_cycle_profit, runtime_order, stop_pair,
)
from app.models import (
    CycleStatus, Event, Order, OrderSide, OrderStatus, PairConfig, PairStatus, TradeCycle,
)
from app.schemas import PairCreate, maximum_order_pairs
from app.services.engine import describe_exception


class FakeSession:
    def __init__(self, pair: PairConfig) -> None:
        self.pair = pair
        self.added: list[object] = []
        self.committed = False

    async def get(self, model, pair_id):
        return self.pair if model is PairConfig and pair_id == self.pair.id else None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, value: object) -> None:
        pass


@pytest.mark.parametrize(("side", "market_price", "order_price", "expected"), [
    (OrderSide.BUY, Decimal("100"), Decimal("99.5"), Decimal("0.5")),
    (OrderSide.SELL, Decimal("100"), Decimal("100.75"), Decimal("0.75")),
    (OrderSide.BUY, Decimal("99"), Decimal("99.5"), Decimal("0")),
    (OrderSide.SELL, Decimal("101"), Decimal("100.75"), Decimal("0")),
])
def test_order_distance_pct_counts_down_to_execution_price(
    side: OrderSide, market_price: Decimal, order_price: Decimal, expected: Decimal
) -> None:
    assert order_distance_pct(side, market_price, order_price) == expected


def test_order_distance_pct_is_unavailable_without_market_price() -> None:
    assert order_distance_pct(OrderSide.BUY, None, Decimal("99.5")) is None


def test_order_distance_values_include_price_and_percentage() -> None:
    distance, percentage = order_distance_values(
        OrderSide.SELL, Decimal("100"), Decimal("100.75")
    )
    assert distance == Decimal("0.75")
    assert percentage == Decimal("0.75")


def test_runtime_order_reports_remaining_distance_for_open_order() -> None:
    order = Order(
        id=uuid.uuid4(),
        exchange_order_id="exchange-order-1",
        client_order_id="client-order-1",
        side=OrderSide.BUY,
        status=OrderStatus.PARTIALLY_FILLED,
        price=Decimal("99"),
        quantity=Decimal("2"),
        executed_quantity=Decimal("0.5"),
    )

    result = runtime_order(order, Decimal("100"))

    assert result.execution_pct == Decimal("25")
    assert result.exchange_order_id == "exchange-order-1"
    assert result.client_order_id == "client-order-1"
    assert result.distance_price == Decimal("1")
    assert result.distance_pct == Decimal("1")


def test_runtime_order_hides_distance_after_fill() -> None:
    order = Order(
        id=uuid.uuid4(),
        exchange_order_id="exchange-order-2",
        client_order_id="client-order-2",
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        price=Decimal("101"),
        quantity=Decimal("1"),
        executed_quantity=Decimal("1"),
    )

    result = runtime_order(order, Decimal("100"))

    assert result.distance_price is None
    assert result.distance_pct is None
    assert result.execution_pct == Decimal("100")


@pytest.mark.parametrize(("side", "market_price", "expected_trigger", "expected_distance"), [
    (OrderSide.BUY, Decimal("99.5"), Decimal("99"), Decimal("0.5025125628140703517587939698")),
    (OrderSide.SELL, Decimal("100.5"), Decimal("101"), Decimal("0.4975124378109452736318407960")),
    (OrderSide.BUY, Decimal("98.9"), Decimal("99"), Decimal("0")),
    (OrderSide.SELL, Decimal("101.1"), Decimal("101"), Decimal("0")),
])
def test_red_line_values_match_engine_direction(
    side: OrderSide,
    market_price: Decimal,
    expected_trigger: Decimal,
    expected_distance: Decimal,
) -> None:
    trigger, distance = red_line_values(side, Decimal("100"), market_price, Decimal("1"))
    assert trigger == expected_trigger
    assert distance == expected_distance


def test_red_line_values_keep_trigger_without_market_price() -> None:
    trigger, distance = red_line_values(
        OrderSide.SELL, Decimal("63830.34"), None, Decimal("1")
    )
    assert trigger == Decimal("64468.6434")
    assert distance is None


@pytest.mark.asyncio
async def test_manual_stop_preserves_existing_exchange_orders() -> None:
    pair = PairConfig(
        id=uuid.uuid4(),
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        lot_quote=Decimal("100"),
        spread_pct=Decimal("0.15"),
        base_balance_trigger=Decimal("0.01"),
        base_balance_limit=Decimal("0.005"),
        quote_balance_trigger=Decimal("500"),
        quote_balance_limit=Decimal("200"),
        order_offset_pct=Decimal("0.005"),
        red_line_pct=Decimal("0.5"),
        enabled=True,
        status=PairStatus.RUNNING,
    )
    session = FakeSession(pair)

    result = await stop_pair(pair.id, session=session)

    assert result is pair
    assert pair.enabled is False
    assert pair.status == PairStatus.STOPPED
    assert session.committed is True
    event = next(item for item in session.added if isinstance(item, Event))
    assert event.kind == "manual_stop"
    assert "checked on restart" in event.message


def test_paper_profit_excludes_red_line_market_pnl_but_keeps_commission() -> None:
    cycle = TradeCycle(
        status=CycleStatus.RED_LINE,
        gross_profit_quote=Decimal("-2.5"),
        commission_quote=Decimal("0.1"),
        net_profit_quote=Decimal("-2.6"),
    )

    assert reported_cycle_profit(cycle, True) == (
        Decimal("0"),
        Decimal("0.1"),
        Decimal("-0.1"),
    )


def test_disabled_paper_profit_keeps_current_red_line_result() -> None:
    cycle = TradeCycle(
        status=CycleStatus.RED_LINE,
        gross_profit_quote=Decimal("-2.5"),
        commission_quote=Decimal("0.1"),
        net_profit_quote=Decimal("-2.6"),
    )

    assert reported_cycle_profit(cycle, False) == (
        Decimal("-2.5"),
        Decimal("0.1"),
        Decimal("-2.6"),
    )


def test_paper_profit_keeps_profitable_cycle_result() -> None:
    cycle = TradeCycle(
        status=CycleStatus.PROFITABLE,
        gross_profit_quote=Decimal("1.5"),
        commission_quote=Decimal("0.1"),
        net_profit_quote=Decimal("1.4"),
    )

    assert reported_cycle_profit(cycle, True) == (
        Decimal("1.5"),
        Decimal("0.1"),
        Decimal("1.4"),
    )


def test_engine_error_without_message_is_still_actionable() -> None:
    assert describe_exception(TimeoutError()) == "TimeoutError: no message; args=()"


def test_engine_error_includes_cause_chain() -> None:
    try:
        try:
            raise ConnectionError("exchange disconnected")
        except ConnectionError as cause:
            raise RuntimeError("order refresh failed") from cause
    except RuntimeError as error:
        assert describe_exception(error) == (
            "RuntimeError: order refresh failed <- caused by "
            "ConnectionError: exchange disconnected"
        )


def test_grid_capacity_fits_inside_red_line() -> None:
    assert maximum_order_pairs(Decimal("0.15"), Decimal("1")) == 6


def test_pair_schema_rejects_grid_outside_red_line() -> None:
    with pytest.raises(ValueError, match="order_pair_count cannot exceed 6"):
        PairCreate(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            lot_quote=Decimal("100"),
            spread_pct=Decimal("0.15"),
            base_balance_trigger=Decimal("0.01"),
            base_balance_limit=Decimal("0.005"),
            quote_balance_trigger=Decimal("500"),
            quote_balance_limit=Decimal("200"),
            order_offset_pct=Decimal("0.005"),
            red_line_pct=Decimal("1"),
            pause_minutes=1,
            price_precision=2,
            quantity_precision=6,
            order_pair_count=7,
        )


def test_month_period_boundaries() -> None:
    from datetime import datetime, timezone

    start = _period_start(datetime(2026, 12, 25, 12, tzinfo=timezone.utc), "month")
    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert _next_period(start, "month") == datetime(2027, 1, 1, tzinfo=timezone.utc)

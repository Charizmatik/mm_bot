import uuid
from decimal import Decimal

import pytest

from app.api import _next_period, _period_start, order_distance_pct, reported_cycle_profit, stop_pair
from app.models import CycleStatus, Event, OrderSide, PairConfig, PairStatus, TradeCycle
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


def test_month_period_boundaries() -> None:
    from datetime import datetime, timezone

    start = _period_start(datetime(2026, 12, 25, 12, tzinfo=timezone.utc), "month")
    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert _next_period(start, "month") == datetime(2027, 1, 1, tzinfo=timezone.utc)

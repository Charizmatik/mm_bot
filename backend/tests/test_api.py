import uuid
from decimal import Decimal

import pytest

from app.api import reported_cycle_profit, stop_pair
from app.models import CycleStatus, Event, PairConfig, PairStatus, TradeCycle


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


def test_paper_profit_excludes_red_line_pnl_from_reported_result() -> None:
    cycle = TradeCycle(
        status=CycleStatus.RED_LINE,
        gross_profit_quote=Decimal("-2.5"),
        commission_quote=Decimal("0.1"),
        net_profit_quote=Decimal("-2.6"),
    )

    assert reported_cycle_profit(cycle, True) == (Decimal("0"), Decimal("0"), Decimal("0"))


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

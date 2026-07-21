import uuid
from decimal import Decimal

import pytest

from app.api import stop_pair
from app.models import Event, PairConfig, PairStatus


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

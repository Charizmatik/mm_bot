from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.services.engine as engine_module
from app.api import _equity_snapshot_reads
from app.config import Settings
from app.exchanges.base import AssetBalance, Exchange, Quote
from app.models import AccountEquitySnapshot, Base
from app.services.engine import MarketMakerEngine


class EquityExchange(Exchange):
    async def balances(self):
        return {
            "USDT": AssetBalance(Decimal("100")),
            "BTC": AssetBalance(Decimal("0.01")),
            "DUST": AssetBalance(Decimal("2")),
        }

    async def book_quote(self, symbol: str):
        if symbol == "BTCUSDT":
            return Quote(symbol, Decimal("50000"), Decimal("50001"))
        raise RuntimeError("symbol unavailable")

    async def place_limit(self, *args, **kwargs):
        raise NotImplementedError

    async def order(self, *args, **kwargs):
        raise NotImplementedError

    async def cancel(self, *args, **kwargs):
        raise NotImplementedError

    async def fills(self, *args, **kwargs):
        raise NotImplementedError

    async def symbols(self):
        return []

    async def stream_quotes(self, symbols, handler):
        return None

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_daily_snapshot_values_assets_at_liquidation_bid(monkeypatch) -> None:
    database = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with database.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(database, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "SessionLocal", sessions)

    engine = MarketMakerEngine(
        EquityExchange(), Settings(account_snapshot_timezone="Europe/Kyiv")
    )
    created = await engine.capture_account_equity_if_missing()

    assert created is not None
    assert created.equity_usdt == Decimal("600")
    assert created.priced_assets == 2
    assert created.unpriced_assets == 1
    assert await engine.capture_account_equity_if_missing() is None

    async with sessions() as session:
        stored = await session.scalar(select(AccountEquitySnapshot))
        assert stored is not None
        btc = next(asset for asset in stored.assets if asset.asset == "BTC")
        assert btc.price_usdt == Decimal("50000")
        assert btc.value_usdt == Decimal("500")
        assert btc.valuation_source == "BTCUSDT.bid"

    await database.dispose()


def test_equity_history_calculates_change_and_percentage() -> None:
    first = AccountEquitySnapshot(
        id=uuid.uuid4(),
        snapshot_date=date(2026, 8, 3),
        timezone="Europe/Kyiv",
        captured_at=datetime(2026, 8, 2, 21, tzinfo=timezone.utc),
        equity_usdt=Decimal("1000"),
        priced_assets=1,
        unpriced_assets=0,
        assets=[],
    )
    second = AccountEquitySnapshot(
        id=uuid.uuid4(),
        snapshot_date=date(2026, 8, 4),
        timezone="Europe/Kyiv",
        captured_at=datetime(2026, 8, 3, 21, tzinfo=timezone.utc),
        equity_usdt=Decimal("1015"),
        priced_assets=1,
        unpriced_assets=0,
        assets=[],
    )

    result = _equity_snapshot_reads([first, second])

    assert result[0].change_usdt is None
    assert result[1].change_usdt == Decimal("15")
    assert result[1].change_pct == Decimal("1.5")

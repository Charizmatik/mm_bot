import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    Base,
    CycleStatus,
    Order,
    OrderSide,
    OrderStatus,
    PairConfig,
    TradeCycle,
    TradeFill,
)


@pytest.mark.asyncio
async def test_engine_collections_are_eagerly_available_with_async_session() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    pair_id = uuid.uuid4()
    async with session_factory() as session:
        cycle = TradeCycle(
            pair_id=pair_id,
            status=CycleStatus.OPEN,
            reference_bid=Decimal("99.9"),
            reference_ask=Decimal("100.1"),
            orders=[
                Order(
                    exchange_order_id="exchange-order-1",
                    client_order_id="client-order-1",
                    side=OrderSide.BUY,
                    status=OrderStatus.FILLED,
                    price=Decimal("99.9"),
                    quantity=Decimal("0.1"),
                    executed_quantity=Decimal("0.1"),
                    fills=[
                        TradeFill(
                            exchange_trade_id="exchange-trade-1",
                            price=Decimal("99.9"),
                            quantity=Decimal("0.1"),
                            quote_quantity=Decimal("9.99"),
                            commission=Decimal("0"),
                            commission_asset="USDT",
                            commission_quote=Decimal("0"),
                        )
                    ],
                )
            ],
        )
        session.add(
            PairConfig(
                id=pair_id,
                symbol="ETHUSDT",
                base_asset="ETH",
                quote_asset="USDT",
                lot_quote=Decimal("10"),
                spread_pct=Decimal("0.2"),
                base_balance_trigger=Decimal("0"),
                base_balance_limit=Decimal("0"),
                quote_balance_trigger=Decimal("0"),
                quote_balance_limit=Decimal("0"),
                order_offset_pct=Decimal("0"),
                red_line_pct=Decimal("1"),
                pause_minutes=1,
                price_precision=2,
                quantity_precision=4,
                order_pair_count=3,
                cycles=[cycle],
            )
        )
        await session.commit()

    async with session_factory() as session:
        loaded_cycle = await session.scalar(select(TradeCycle))

        assert loaded_cycle is not None
        assert len(loaded_cycle.orders) == 1
        assert len(loaded_cycle.orders[0].fills) == 1

    await engine.dispose()

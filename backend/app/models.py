import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class PairStatus(str, enum.Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    LIMIT_REACHED = "limit_reached"
    ERROR = "error"


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, enum.Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class CycleStatus(str, enum.Enum):
    OPEN = "open"
    PROFITABLE = "profitable"
    RED_LINE = "red_line"
    CANCELED = "canceled"


class PairConfig(Base):
    __tablename__ = "pair_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    exchange: Mapped[str] = mapped_column(String(30), default="mexc")
    symbol: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    base_asset: Mapped[str] = mapped_column(String(20))
    quote_asset: Mapped[str] = mapped_column(String(20), default="USDT")
    lot_quote: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    spread_pct: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    base_balance_trigger: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    base_balance_limit: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    quote_balance_trigger: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    quote_balance_limit: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    base_balance_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    quote_balance_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    order_offset_pct: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    red_line_pct: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    pause_minutes: Mapped[int] = mapped_column(Integer, default=1)
    price_precision: Mapped[int] = mapped_column(Integer, default=2)
    quantity_precision: Mapped[int] = mapped_column(Integer, default=6)
    order_pair_count: Mapped[int] = mapped_column(Integer, default=1)
    # Retained for database compatibility. Neutral grid pricing no longer
    # reads or mutates this legacy inventory-skew value.
    irb: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[PairStatus] = mapped_column(Enum(PairStatus), default=PairStatus.STOPPED)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    cycles: Mapped[list["TradeCycle"]] = relationship(back_populates="pair")


class TradeCycle(Base):
    __tablename__ = "trade_cycles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pair_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pair_configs.id"), index=True)
    status: Mapped[CycleStatus] = mapped_column(Enum(CycleStatus), default=CycleStatus.OPEN)
    reference_bid: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    reference_ask: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    gross_profit_quote: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("0"))
    commission_quote: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("0"))
    net_profit_quote: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("0"))
    mark_price: Mapped[Decimal | None] = mapped_column(Numeric(30, 12), nullable=True)
    grid_slot: Mapped[int] = mapped_column(Integer, default=0)
    retiring: Mapped[bool] = mapped_column(Boolean, default=False)
    successor_spawned: Mapped[bool] = mapped_column(Boolean, default=False)
    replacement_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pair: Mapped[PairConfig] = relationship(back_populates="cycles")
    orders: Mapped[list["Order"]] = relationship(back_populates="cycle", cascade="all, delete-orphan")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trade_cycles.id"), index=True)
    exchange_order_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.NEW)
    price: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    executed_quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    cycle: Mapped[TradeCycle] = relationship(back_populates="orders")
    fills: Mapped[list["TradeFill"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class TradeFill(Base):
    __tablename__ = "trade_fills"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    exchange_trade_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    quote_quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    quote_quantity_usdt: Mapped[Decimal | None] = mapped_column(Numeric(30, 12), nullable=True)
    commission: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("0"))
    commission_asset: Mapped[str] = mapped_column(String(20))
    commission_quote: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("0"))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="fills")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pair_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pair_configs.id"), nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(20), default="info")
    kind: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import CycleStatus, OrderSide, OrderStatus, PairStatus


class PairCreate(BaseModel):
    symbol: str = Field(pattern=r"^[A-Za-z0-9_/-]{5,30}$")
    base_asset: str = Field(min_length=2, max_length=20)
    quote_asset: str = Field(default="USDT", min_length=2, max_length=20)
    lot_quote: Decimal = Field(gt=0)
    spread_pct: Decimal = Field(gt=0, le=10)
    base_balance_trigger: Decimal = Field(gt=0)
    base_balance_limit: Decimal = Field(gt=0)
    quote_balance_trigger: Decimal = Field(gt=0)
    quote_balance_limit: Decimal = Field(gt=0)
    order_offset_pct: Decimal = Field(gt=0, le=10)
    red_line_pct: Decimal = Field(gt=0, le=50)
    pause_minutes: int = Field(ge=0, le=1440)
    price_precision: int = Field(ge=0, le=18)
    quantity_precision: int = Field(default=6, ge=0, le=18)

    @model_validator(mode="after")
    def validate_strategy(self) -> "PairCreate":
        if self.base_balance_trigger <= self.base_balance_limit:
            raise ValueError("base balance trigger must be greater than base balance limit")
        if self.quote_balance_trigger <= self.quote_balance_limit:
            raise ValueError("quote balance trigger must be greater than quote balance limit")
        if self.order_offset_pct >= self.spread_pct:
            raise ValueError("order_offset_pct must be smaller than spread_pct")
        return self


class PairUpdate(PairCreate):
    pass


class PairRead(PairCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    exchange: str
    irb: int
    status: PairStatus
    enabled: bool
    paused_until: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ActiveOrderRead(BaseModel):
    price: Decimal
    distance_pct: Decimal | None = None


class PairRuntime(BaseModel):
    pair: PairRead
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_order: ActiveOrderRead | None = None
    ask_order: ActiveOrderRead | None = None
    quote_updated_at: datetime | None = None
    base_free: Decimal | None = None
    quote_free: Decimal | None = None
    balance_updated_at: datetime | None = None
    open_orders: int = 0


class ManualIrb(BaseModel):
    value: int
    note: str = Field(min_length=3, max_length=500)


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    pair_id: uuid.UUID | None
    level: str
    kind: str
    message: str
    created_at: datetime


class Health(BaseModel):
    status: str
    dry_run: bool


class ProfitBucket(BaseModel):
    quote_asset: str
    trading_volume: Decimal
    trading_volume_usdt: Decimal
    gross_profit: Decimal
    commission: Decimal
    net_profit: Decimal


class PairStatistics(ProfitBucket):
    pair_id: uuid.UUID
    symbol: str
    successful_trades: int
    unsuccessful_trades: int
    total_trades: int
    success_rate_pct: Decimal


class Statistics(BaseModel):
    successful_trades: int
    unsuccessful_trades: int
    total_trades: int
    success_rate_pct: Decimal
    by_quote_asset: list[ProfitBucket]
    pairs: list[PairStatistics]


class FillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    exchange_trade_id: str
    price: Decimal
    quantity: Decimal
    quote_quantity: Decimal
    quote_quantity_usdt: Decimal | None
    commission: Decimal
    commission_asset: str
    commission_quote: Decimal
    executed_at: datetime


class OrderRead(BaseModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    pair_id: uuid.UUID
    symbol: str
    base_asset: str
    quote_asset: str
    cycle_status: CycleStatus
    exchange_order_id: str
    client_order_id: str
    side: OrderSide
    status: OrderStatus
    price: Decimal
    quantity: Decimal
    executed_quantity: Decimal
    quote_value: Decimal
    execution_pct: Decimal
    created_at: datetime
    updated_at: datetime
    fills: list[FillRead]


class SymbolRead(BaseModel):
    symbol: str
    base_asset: str
    quote_asset: str
    price_precision: int
    quantity_precision: int

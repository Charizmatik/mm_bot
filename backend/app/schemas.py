import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import CycleStatus, OrderSide, OrderStatus, PairStatus


GRID_GAP_PCT = Decimal("0.001")


def maximum_order_pairs(spread_pct: Decimal, red_line_pct: Decimal) -> int:
    return max(1, int(red_line_pct // (spread_pct + GRID_GAP_PCT)))


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
    order_pair_count: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_strategy(self) -> "PairCreate":
        if self.base_balance_trigger <= self.base_balance_limit:
            raise ValueError("base balance trigger must be greater than base balance limit")
        if self.quote_balance_trigger <= self.quote_balance_limit:
            raise ValueError("quote balance trigger must be greater than quote balance limit")
        if self.order_offset_pct >= self.spread_pct:
            raise ValueError("order_offset_pct must be smaller than spread_pct")
        maximum = maximum_order_pairs(self.spread_pct, self.red_line_pct)
        if self.order_pair_count > maximum:
            raise ValueError(
                f"order_pair_count cannot exceed {maximum} for the configured spread and red line"
            )
        return self


class PairUpdate(PairCreate):
    pass


class PairRead(PairCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    exchange: str
    status: PairStatus
    enabled: bool
    paused_until: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ActiveOrderRead(BaseModel):
    price: Decimal
    distance_pct: Decimal | None = None


class RedLineRead(BaseModel):
    filled_side: OrderSide
    reference_price: Decimal
    trigger_price: Decimal
    distance_price: Decimal | None = None
    distance_pct: Decimal | None = None


class RuntimeOrderRead(BaseModel):
    id: uuid.UUID
    side: OrderSide
    status: OrderStatus
    price: Decimal
    quantity: Decimal
    executed_quantity: Decimal
    execution_pct: Decimal
    distance_price: Decimal | None = None
    distance_pct: Decimal | None = None


class RuntimeOrderPairRead(BaseModel):
    cycle_id: uuid.UUID
    grid_slot: int
    retiring: bool
    successor_spawned: bool
    opened_at: datetime
    buy_order: RuntimeOrderRead
    sell_order: RuntimeOrderRead
    red_line: RedLineRead | None = None


class PairRuntime(BaseModel):
    pair: PairRead
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_order: ActiveOrderRead | None = None
    ask_order: ActiveOrderRead | None = None
    red_line: RedLineRead | None = None
    quote_updated_at: datetime | None = None
    base_free: Decimal | None = None
    quote_free: Decimal | None = None
    base_trigger_price: Decimal | None = None
    base_limit_price: Decimal | None = None
    quote_trigger_price: Decimal | None = None
    quote_limit_price: Decimal | None = None
    balance_updated_at: datetime | None = None
    open_orders: int = 0
    active_order_pairs: int = 0
    retiring_order_pairs: int = 0
    order_pairs: list[RuntimeOrderPairRead] = Field(default_factory=list)


class OrderPairCountUpdate(BaseModel):
    value: int = Field(ge=1)


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    pair_id: uuid.UUID | None
    level: str
    kind: str
    message: str
    created_at: datetime


class EventPage(BaseModel):
    items: list[EventRead]
    total: int
    page: int
    page_size: int
    pages: int


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


class OrderPage(BaseModel):
    items: list[OrderRead]
    total: int
    page: int
    page_size: int
    pages: int


class AnalyticsPeriod(BaseModel):
    period_start: datetime
    period_end: datetime
    successful_trades: int
    unsuccessful_trades: int
    total_trades: int
    success_rate_pct: Decimal
    trading_volume_usdt: Decimal
    by_quote_asset: list[ProfitBucket]


class AnalyticsReport(BaseModel):
    date_from: datetime | None
    date_to: datetime
    granularity: str
    totals: Statistics
    periods: list[AnalyticsPeriod]


class SymbolRead(BaseModel):
    symbol: str
    base_asset: str
    quote_asset: str
    price_precision: int
    quantity_precision: int

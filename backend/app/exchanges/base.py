from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from app.models import OrderSide, OrderStatus


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal


@dataclass(frozen=True)
class AssetBalance:
    free: Decimal
    locked: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.free + self.locked


@dataclass(frozen=True)
class ExchangeOrder:
    order_id: str
    client_order_id: str
    status: OrderStatus
    executed_quantity: Decimal


@dataclass(frozen=True)
class ExchangeFill:
    trade_id: str
    price: Decimal
    quantity: Decimal
    quote_quantity: Decimal
    commission: Decimal
    commission_asset: str


@dataclass(frozen=True)
class ExchangeSymbol:
    symbol: str
    base_asset: str
    quote_asset: str
    price_precision: int
    quantity_precision: int


QuoteHandler = Callable[[Quote], Awaitable[None]]


class Exchange(ABC):
    @abstractmethod
    async def balances(self) -> dict[str, AssetBalance]: ...

    @abstractmethod
    async def place_limit(
        self, symbol: str, side: OrderSide, quantity: Decimal, price: Decimal, client_order_id: str
    ) -> ExchangeOrder: ...

    @abstractmethod
    async def order(self, symbol: str, order_id: str) -> ExchangeOrder: ...

    @abstractmethod
    async def cancel(self, symbol: str, order_id: str) -> ExchangeOrder: ...

    @abstractmethod
    async def fills(self, symbol: str, order_id: str) -> list[ExchangeFill]: ...

    @abstractmethod
    async def book_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    async def symbols(self) -> list[ExchangeSymbol]: ...

    @abstractmethod
    async def stream_quotes(self, symbols: set[str], handler: QuoteHandler) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

import asyncio
import uuid
from decimal import Decimal

import httpx

from app.exchanges.base import (
    AssetBalance,
    Exchange,
    ExchangeFill,
    ExchangeOrder,
    ExchangeSymbol,
    Quote,
    QuoteHandler,
)
from app.exchanges.mexc import parse_symbols
from app.models import OrderSide, OrderStatus


class PaperExchange(Exchange):
    """Dry-run exchange: live public prices, entirely local fake orders."""

    def __init__(self, balance_source: Exchange | None = None, maker_fee_pct: Decimal = Decimal("0.1")) -> None:
        self.client = httpx.AsyncClient(base_url="https://api.mexc.com", timeout=10)
        self.balance_source = balance_source
        self.maker_fee_pct = maker_fee_pct
        self._orders: dict[str, dict] = {}
        self._quotes: dict[str, Quote] = {}
        self._closed = False

    async def balances(self) -> dict[str, AssetBalance]:
        if self.balance_source:
            return await self.balance_source.balances()
        return {}

    async def place_limit(
        self, symbol: str, side: OrderSide, quantity: Decimal, price: Decimal, client_order_id: str
    ) -> ExchangeOrder:
        quote = self._quotes.get(symbol)
        if quote and (
            (side == OrderSide.BUY and price >= quote.ask)
            or (side == OrderSide.SELL and price <= quote.bid)
        ):
            raise RuntimeError("post-only order would execute immediately")
        order_id = f"paper-{uuid.uuid4().hex}"
        self._orders[order_id] = {"symbol": symbol, "side": side, "quantity": quantity, "price": price,
                                  "client_order_id": client_order_id, "status": OrderStatus.NEW}
        return ExchangeOrder(order_id, client_order_id, OrderStatus.NEW, Decimal("0"))

    def _fill_if_crossed(self, value: dict) -> None:
        quote = self._quotes.get(value["symbol"])
        if not quote or value["status"] != OrderStatus.NEW:
            return
        if (value["side"] == OrderSide.BUY and quote.ask <= value["price"]) or (
            value["side"] == OrderSide.SELL and quote.bid >= value["price"]
        ):
            value["status"] = OrderStatus.FILLED

    async def order(self, symbol: str, order_id: str) -> ExchangeOrder:
        value = self._orders[order_id]
        self._fill_if_crossed(value)
        executed = value["quantity"] if value["status"] == OrderStatus.FILLED else Decimal("0")
        return ExchangeOrder(order_id, value["client_order_id"], value["status"], executed)

    async def cancel(self, symbol: str, order_id: str) -> ExchangeOrder:
        value = self._orders[order_id]
        if value["status"] == OrderStatus.NEW:
            value["status"] = OrderStatus.CANCELED
        return await self.order(symbol, order_id)

    async def fills(self, symbol: str, order_id: str) -> list[ExchangeFill]:
        value = self._orders[order_id]
        self._fill_if_crossed(value)
        if value["status"] != OrderStatus.FILLED:
            return []
        quote_quantity = value["price"] * value["quantity"]
        return [ExchangeFill(
            trade_id=f"{order_id}-fill",
            price=value["price"],
            quantity=value["quantity"],
            quote_quantity=quote_quantity,
            commission=quote_quantity * self.maker_fee_pct / Decimal("100"),
            commission_asset="__QUOTE__",
        )]

    async def book_quote(self, symbol: str) -> Quote:
        cached = self._quotes.get(symbol)
        if cached:
            return cached
        response = await self.client.get("/api/v3/ticker/bookTicker", params={"symbol": symbol})
        response.raise_for_status()
        data = response.json()
        return Quote(symbol, Decimal(data["bidPrice"]), Decimal(data["askPrice"]))

    async def symbols(self) -> list[ExchangeSymbol]:
        response = await self.client.get("/api/v3/exchangeInfo")
        response.raise_for_status()
        return parse_symbols(response.json())

    async def stream_quotes(self, symbols: set[str], handler: QuoteHandler) -> None:
        while not self._closed:
            for symbol in symbols:
                try:
                    response = await self.client.get("/api/v3/ticker/bookTicker", params={"symbol": symbol})
                    response.raise_for_status()
                    data = response.json()
                    quote = Quote(symbol, Decimal(data["bidPrice"]), Decimal(data["askPrice"]))
                    self._quotes[symbol] = quote
                    await handler(quote)
                except (httpx.HTTPError, KeyError, ValueError):
                    pass
            await asyncio.sleep(1)

    async def close(self) -> None:
        self._closed = True
        await self.client.aclose()
        if self.balance_source:
            await self.balance_source.close()

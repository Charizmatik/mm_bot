import asyncio
import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import websockets

from app.exchanges.base import Exchange, ExchangeFill, ExchangeOrder, ExchangeSymbol, Quote, QuoteHandler
from app.exchanges.mexc_proto import parse_book_ticker
from app.models import OrderSide, OrderStatus


class MexcError(RuntimeError):
    pass


def parse_symbols(data: dict) -> list[ExchangeSymbol]:
    result = []
    for item in data.get("symbols", []):
        permissions = item.get("permissions", [])
        if item.get("isSpotTradingAllowed") is False or (permissions and "SPOT" not in permissions):
            continue
        result.append(ExchangeSymbol(
            symbol=str(item["symbol"]),
            base_asset=str(item["baseAsset"]),
            quote_asset=str(item["quoteAsset"]),
            price_precision=int(item.get("quotePrecision", item.get("quoteAssetPrecision", 8))),
            quantity_precision=int(item.get("baseAssetPrecision", 8)),
        ))
    return result


class MexcExchange(Exchange):
    REST_URL = "https://api.mexc.com"
    WS_URL = "wss://wbs-api.mexc.com/ws"

    def __init__(self, api_key: str, api_secret: str) -> None:
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.client = httpx.AsyncClient(base_url=self.REST_URL, timeout=10)
        self._closed = False

    def _signed(self, params: dict[str, str | int]) -> dict[str, str | int]:
        if not self.api_key or not self.api_secret:
            raise MexcError("MEXC_API_KEY and MEXC_API_SECRET are required for live mode")
        params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": 5000}
        params["signature"] = hmac.new(self.api_secret, urlencode(params).encode(), hashlib.sha256).hexdigest()
        return params

    async def _private(self, method: str, path: str, params: dict) -> dict:
        response = await self.client.request(
            method, path, params=self._signed(params), headers={"X-MEXC-APIKEY": self.api_key}
        )
        if response.is_error:
            raise MexcError(f"MEXC {response.status_code}: {response.text[:300]}")
        return response.json()

    async def balances(self) -> dict[str, Decimal]:
        data = await self._private("GET", "/api/v3/account", {})
        return {item["asset"]: Decimal(item["free"]) for item in data.get("balances", [])}

    @staticmethod
    def _normalize(data: dict) -> ExchangeOrder:
        raw_status = data.get("status", "NEW")
        try:
            status = OrderStatus(raw_status)
        except ValueError:
            status = OrderStatus.REJECTED
        return ExchangeOrder(
            order_id=str(data["orderId"]),
            client_order_id=data.get("clientOrderId", data.get("origClientOrderId", "")),
            status=status,
            executed_quantity=Decimal(str(data.get("executedQty", "0"))),
        )

    async def place_limit(
        self, symbol: str, side: OrderSide, quantity: Decimal, price: Decimal, client_order_id: str
    ) -> ExchangeOrder:
        data = await self._private("POST", "/api/v3/order", {
            "symbol": symbol, "side": side.value, "type": "LIMIT", "timeInForce": "GTC",
            "quantity": format(quantity, "f"), "price": format(price, "f"),
            "newClientOrderId": client_order_id,
        })
        return self._normalize(data)

    async def order(self, symbol: str, order_id: str) -> ExchangeOrder:
        return self._normalize(await self._private("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}))

    async def cancel(self, symbol: str, order_id: str) -> ExchangeOrder:
        return self._normalize(await self._private("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}))

    async def fills(self, symbol: str, order_id: str) -> list[ExchangeFill]:
        data = await self._private(
            "GET", "/api/v3/myTrades", {"symbol": symbol, "orderId": order_id, "limit": 100}
        )
        return [
            ExchangeFill(
                trade_id=str(item["id"]),
                price=Decimal(str(item["price"])),
                quantity=Decimal(str(item["qty"])),
                quote_quantity=Decimal(str(item.get("quoteQty", Decimal(item["price"]) * Decimal(item["qty"])))),
                commission=Decimal(str(item.get("commission", "0"))),
                commission_asset=str(item.get("commissionAsset", "")),
            )
            for item in data
            if str(item.get("orderId")) == str(order_id)
        ]

    async def book_quote(self, symbol: str) -> Quote:
        response = await self.client.get("/api/v3/ticker/bookTicker", params={"symbol": symbol})
        response.raise_for_status()
        data = response.json()
        return Quote(symbol, Decimal(data["bidPrice"]), Decimal(data["askPrice"]))

    async def symbols(self) -> list[ExchangeSymbol]:
        response = await self.client.get("/api/v3/exchangeInfo")
        response.raise_for_status()
        return parse_symbols(response.json())

    async def stream_quotes(self, symbols: set[str], handler: QuoteHandler) -> None:
        if not symbols:
            await asyncio.sleep(1)
            return
        delay = 1
        while not self._closed:
            try:
                async with websockets.connect(self.WS_URL, ping_interval=20, ping_timeout=10) as socket:
                    params = [f"spot@public.aggre.bookTicker.v3.api.pb@100ms@{symbol}" for symbol in sorted(symbols)]
                    await socket.send(json.dumps({"method": "SUBSCRIPTION", "params": params}))
                    delay = 1
                    async for payload in socket:
                        if isinstance(payload, str):
                            continue
                        parsed = parse_book_ticker(payload)
                        if parsed:
                            symbol, bid, ask = parsed
                            await handler(Quote(symbol, Decimal(bid), Decimal(ask)))
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def close(self) -> None:
        self._closed = True
        await self.client.aclose()

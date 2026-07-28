import time
from decimal import Decimal

import httpx
import pytest

from app.config import Settings
from app.exchanges.mexc import MexcError, MexcExchange
from app.models import OrderSide, OrderStatus
from app.services.engine import MarketMakerEngine


async def _exchange_with_transport(handler) -> MexcExchange:
    exchange = MexcExchange("key", "secret", recv_window_ms=10_000)
    await exchange.client.aclose()
    exchange.client = httpx.AsyncClient(
        base_url=exchange.REST_URL,
        transport=httpx.MockTransport(handler),
        timeout=10,
    )
    return exchange


@pytest.mark.asyncio
async def test_private_request_resynchronizes_and_retries_timestamp_error() -> None:
    calls: list[str] = []
    account_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal account_attempts
        calls.append(request.url.path)
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": int(time.time() * 1000) + 75})
        if request.url.path == "/api/v3/account":
            account_attempts += 1
            assert request.url.params["recvWindow"] == "10000"
            if account_attempts == 1:
                return httpx.Response(
                    400,
                    json={"code": 700003, "msg": "Timestamp for this request is outside of the recvWindow."},
                )
            return httpx.Response(
                200,
                json={"balances": [{"asset": "USDT", "free": "12.5", "locked": "3.25"}]},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    exchange = await _exchange_with_transport(handler)
    try:
        balances = await exchange.balances()
    finally:
        await exchange.close()

    assert balances["USDT"].free == Decimal("12.5")
    assert balances["USDT"].locked == Decimal("3.25")
    assert balances["USDT"].total == Decimal("15.75")
    assert calls == ["/api/v3/time", "/api/v3/account", "/api/v3/time", "/api/v3/account"]


@pytest.mark.asyncio
async def test_private_error_identifies_endpoint_after_single_retry() -> None:
    account_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal account_attempts
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": int(time.time() * 1000)})
        account_attempts += 1
        return httpx.Response(400, json={"code": 700003, "msg": "bad timestamp"})

    exchange = await _exchange_with_transport(handler)
    try:
        with pytest.raises(MexcError, match=r"MEXC GET /api/v3/account 400"):
            await exchange.balances()
    finally:
        await exchange.close()

    assert account_attempts == 2


@pytest.mark.asyncio
async def test_private_get_retries_read_timeout() -> None:
    account_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal account_attempts
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": int(time.time() * 1000)})
        account_attempts += 1
        if account_attempts < 3:
            raise httpx.ReadTimeout("", request=request)
        return httpx.Response(200, json={"balances": []})

    exchange = await _exchange_with_transport(handler)
    try:
        assert await exchange.balances() == {}
    finally:
        await exchange.close()

    assert account_attempts == 3


@pytest.mark.asyncio
async def test_timed_out_order_placement_recovers_by_client_order_id() -> None:
    post_attempts = 0
    lookup_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_attempts, lookup_attempts
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": int(time.time() * 1000)})
        if request.method == "POST":
            post_attempts += 1
            raise httpx.ReadTimeout("", request=request)
        lookup_attempts += 1
        assert request.url.params["origClientOrderId"] == "client-order-1"
        return httpx.Response(200, json={
            "orderId": "exchange-order-1",
            "clientOrderId": "client-order-1",
            "status": "NEW",
            "executedQty": "0",
        })

    exchange = await _exchange_with_transport(handler)
    try:
        order = await exchange.place_limit(
            "ETHUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("100"),
            client_order_id="client-order-1",
        )
    finally:
        await exchange.close()

    assert order.order_id == "exchange-order-1"
    assert order.status == OrderStatus.NEW
    assert post_attempts == 1
    assert lookup_attempts == 1


def test_quote_staleness_uses_monotonic_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = MarketMakerEngine(None, Settings(quote_stale_seconds=10))  # type: ignore[arg-type]
    engine._quote_received_monotonic["BTCUSDT"] = 100
    monkeypatch.setattr("app.services.engine.time.monotonic", lambda: 109.9)

    assert not engine._quote_is_stale("BTCUSDT", None)  # type: ignore[arg-type]

    monkeypatch.setattr("app.services.engine.time.monotonic", lambda: 110.1)
    assert engine._quote_is_stale("BTCUSDT", None)  # type: ignore[arg-type]

"""
Unit tests for SharkClient REST API wrapper and SharkWebSocketClient.

Mock external HTTP and WebSocket connections – real API keys are never used.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.brokers.shark_client import RateLimiter, SharkClient, get_shark_client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def shark_client() -> SharkClient:
    """Return a SharkClient with test credentials (settings mocked by _mock_settings)."""
    return SharkClient(
        api_key="test-api-key",
        api_secret="test-api-secret",
        base_url="https://mock-shark.example.com",
    )


# ---------------------------------------------------------------------------
# SIGNATURE GENERATION TESTS
# ---------------------------------------------------------------------------

class TestSignatureGeneration:
    """HMAC-SHA256 signature generation unit tests."""

    def test_signature_is_hex_digest(self):
        """_generate_signature produces a 64-char hex string."""
        sig = SharkClient._generate_signature("secret", "data")
        assert isinstance(sig, str)
        assert len(sig) == 64
        # Deterministic
        assert sig == SharkClient._generate_signature("secret", "data")

    def test_signature_changes_with_different_data(self):
        """Different input data produces different signatures."""
        sig_a = SharkClient._generate_signature("secret", "data-a")
        sig_b = SharkClient._generate_signature("secret", "data-b")
        assert sig_a != sig_b

    def test_signature_changes_with_different_secret(self):
        """Different secrets produce different signatures."""
        sig_a = SharkClient._generate_signature("secret-a", "data")
        sig_b = SharkClient._generate_signature("secret-b", "data")
        assert sig_a != sig_b


class TestSignedHeaders:
    """_signed_headers instance method tests."""

    def test_get_request_headers(self):
        """GET requests sign the query string and include api-key + signature."""
        import time
        ts = str(int(time.time() * 1000))
        query = f"symbol=BTCUSDT&timestamp={ts}"
        client = SharkClient(
            api_key="my-api-key", api_secret="my-secret",
            base_url="https://test.example.com",
        )
        headers = client._signed_headers("GET", query)
        assert headers["api-key"] == "my-api-key"
        assert "signature" in headers
        assert len(headers["signature"]) == 64
        assert headers["Content-Type"] == "application/json"

    def test_post_request_headers(self):
        """POST requests sign the JSON body (compact separators)."""
        body = {"symbol": "BTCUSDT", "side": "BUY", "quantity": 0.01}
        body_str = json.dumps(body, separators=(",", ":"))
        client = SharkClient(
            api_key="api-key-123", api_secret="api-secret-456",
            base_url="https://test.example.com",
        )
        headers = client._signed_headers("POST", "", body_str)
        assert headers["api-key"] == "api-key-123"
        assert "signature" in headers
        assert headers["Content-Type"] == "application/json"

    def test_delete_request_headers(self):
        """DELETE requests sign the query string and include api-key + signature."""
        client = SharkClient(
            api_key="key", api_secret="secret",
            base_url="https://test.example.com",
        )
        headers = client._signed_headers("DELETE", "symbol=ETHUSDT")
        assert headers["api-key"] == "key"
        assert "signature" in headers
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# RATE LIMITER TESTS
# ---------------------------------------------------------------------------

class TestRateLimiter:
    """RateLimiter sliding-window unit tests."""

    @pytest.mark.asyncio
    async def test_acquire_within_limit_does_not_block(self):
        """RateLimiter.acquire() returns immediately when well under the rate."""
        limiter = RateLimiter(rate=100)
        for _ in range(20):
            await limiter.acquire()  # Should complete near-instantly

    @pytest.mark.asyncio
    async def test_acquire_past_limit_enforces_delay(self):
        """Requests beyond the rate introduce delay via asyncio.sleep."""
        limiter = RateLimiter(rate=5)  # 5 req/sec
        # Fire off 10 requests in quick succession
        t0 = asyncio.get_event_loop().time()
        for _ in range(10):
            await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - t0
        # At 5 req/sec, 10 requests should take at least ~1 second of delay
        # (10/5 - 1 = 1 second of throttling beyond the first batch)
        assert elapsed >= 0.8, f"Expected at least 0.8s delay for 10 reqs @ 5/s, got {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# SHARK CLIENT – GET BALANCE (MOCK)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_balance_mock(shark_client: SharkClient):
    """SharkClient.get_account_balance returns the raw exchange response dict."""
    mock_response = {
        "totalEquity": 10000.0,
        "availableBalance": 8000.0,
        "walletBalance": 9000.0,
        "totalInitialMargin": 1000.0,
        "totalUnrealizedProfit": 100.0,
    }

    # Replace _request entirely so no real HTTP is made
    shark_client._request = AsyncMock(return_value=mock_response)

    balance = await shark_client.get_account_balance()

    shark_client._request.assert_called_once_with(
        "GET", "/v1/wallet/futures-wallet/details",
    )
    assert balance["availableBalance"] == 8000.0
    assert balance["totalEquity"] == 10000.0
    assert balance["walletBalance"] == 9000.0


# ---------------------------------------------------------------------------
# SHARK CLIENT – PLACE ORDER SUCCESS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_place_order_success(shark_client: SharkClient):
    """SharkClient.place_order returns exchange response with orderId."""
    mock_response = {
        "orderId": "12345",
        "clientOrderId": "my-client-id-001",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "orderType": "MARKET",
        "status": "FILLED",
        "quantity": 0.01,
        "price": 50000.0,
        "leverage": 10,
    }

    shark_client._request = AsyncMock(return_value=mock_response)

    order = await shark_client.place_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        quantity=0.01,
        leverage=10,
        client_order_id="my-client-id-001",
    )

    # Verify the _request was called with correct method/path
    call_args = shark_client._request.call_args
    assert call_args[0][0] == "POST"
    assert call_args[0][1] == "/v1/order/place-order"

    # Verify the JSON body sent was correctly built
    json_body = call_args[1]["json_body"]
    assert json_body["symbol"] == "BTCUSDT"
    assert json_body["side"] == "BUY"
    assert json_body["orderType"] == "MARKET"
    assert json_body["quantity"] == 0.01
    assert json_body["leverage"] == 10
    assert json_body["clientOrderId"] == "my-client-id-001"

    assert order["orderId"] == "12345"
    assert order["status"] == "FILLED"


@pytest.mark.asyncio
async def test_place_order_with_price(shark_client: SharkClient):
    """LIMIT orders include the price field in the JSON body."""
    mock_response = {"orderId": "limit-999", "status": "NEW", "symbol": "ETHUSDT"}
    shark_client._request = AsyncMock(return_value=mock_response)

    await shark_client.place_order(
        symbol="ETHUSDT",
        side="SELL",
        order_type="LIMIT",
        quantity=1.0,
        price=3500.0,
        leverage=5,
    )

    json_body = shark_client._request.call_args[1]["json_body"]
    assert json_body["price"] == 3500.0
    assert json_body["orderType"] == "LIMIT"


@pytest.mark.asyncio
async def test_place_order_with_stop_price(shark_client: SharkClient):
    """STOP_MARKET orders include stopPrice in the JSON body."""
    mock_response = {"orderId": "stop-555", "status": "NEW"}
    shark_client._request = AsyncMock(return_value=mock_response)

    await shark_client.place_order(
        symbol="BTCUSDT",
        side="SELL",
        order_type="STOP_MARKET",
        quantity=0.5,
        stop_price=48000.0,
        reduce_only=True,
    )

    json_body = shark_client._request.call_args[1]["json_body"]
    assert json_body["stopPrice"] == 48000.0
    assert json_body["reduceOnly"] is True


# ---------------------------------------------------------------------------
# SHARK CLIENT – RATE LIMIT RETRY (3 ATTEMPTS)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limit_retry_three_attempts(monkeypatch, shark_client: SharkClient):
    """When HTTP calls fail with NetworkError, the @retry decorator retries
    up to 3 times before giving up.  Two failures + one success = retry works."""
    call_count = [0]  # Use list for mutable closure

    async def mock_http_request(method, url, *, headers=None, content=None):
        call_count[0] += 1
        if call_count[0] < 3:
            raise httpx.NetworkError("Connection reset by peer")
        # Third attempt succeeds
        return httpx.Response(
            200,
            json={"orderId": "retry-success", "status": "FILLED", "symbol": "ETHUSDT"},
            request=httpx.Request(method, url),
        )

    mock_http = AsyncMock()
    mock_http.get = mock_http_request
    mock_http.request = mock_http_request

    async def _get_mock_client():
        return mock_http

    monkeypatch.setattr(shark_client, "_get_client", _get_mock_client)
    # Bypass rate limiter to isolate retry behaviour
    monkeypatch.setattr(shark_client._rate_limiter, "acquire", AsyncMock())

    result = await shark_client.place_order(
        symbol="ETHUSDT",
        side="SELL",
        order_type="LIMIT",
        quantity=0.5,
        price=3000.0,
        leverage=5,
    )

    assert call_count[0] == 3, f"Expected 3 attempts, got {call_count[0]}"
    assert result["orderId"] == "retry-success"
    assert result["status"] == "FILLED"


@pytest.mark.asyncio
async def test_retry_exhausted_raises_network_error(monkeypatch, shark_client: SharkClient):
    """When all 3 retry attempts fail, the original NetworkError propagates."""
    call_count = [0]

    # ``get_account_balance`` issues a GET request via ``client.get(url, headers=...)``
    async def mock_get(url, *, headers=None):
        call_count[0] += 1
        raise httpx.NetworkError("Persistent connection failure")

    mock_http = AsyncMock()
    mock_http.get = mock_get

    async def _get_mock_client():
        return mock_http

    monkeypatch.setattr(shark_client, "_get_client", _get_mock_client)
    monkeypatch.setattr(shark_client._rate_limiter, "acquire", AsyncMock())

    with pytest.raises(httpx.NetworkError, match="Persistent connection failure"):
        await shark_client.get_account_balance()

    assert call_count[0] == 3, f"Expected 3 attempts before exhaustion, got {call_count[0]}"


# ---------------------------------------------------------------------------
# SHARK CLIENT – WEBSOCKET RECONNECT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_websocket_reconnect_on_disconnect(monkeypatch):
    """SharkWebSocketClient automatically reconnects when the WebSocket drops."""
    import websockets
    from app.brokers import shark_websocket as ws_module

    client = ws_module.SharkWebSocketClient()

    # Mock listen key acquisition
    monkeypatch.setattr(client, "_get_listen_key", AsyncMock(return_value="test-listen-key-abc"))

    # Disable Redis interactions
    monkeypatch.setattr(client, "_ensure_redis", AsyncMock(return_value=AsyncMock()))
    monkeypatch.setattr(client, "_publish_ticker", AsyncMock())
    monkeypatch.setattr(client, "_publish_raw_event", AsyncMock())

    connect_count = [0]
    first_disconnect_seen = asyncio.Event()
    second_connect_done = asyncio.Event()

    async def mock_ws_connect(uri, **kwargs):
        connect_count[0] += 1
        if connect_count[0] == 1:
            # First connection: wait briefly then simulate disconnect
            await asyncio.sleep(0.05)
            first_disconnect_seen.set()
            raise websockets.ConnectionClosed(None, None)
        else:
            # Reconnected successfully
            second_connect_done.set()
            # Block indefinitely (until test ends)
            await asyncio.Event().wait()

    monkeypatch.setattr(ws_module.websockets, "connect", mock_ws_connect)

    task = asyncio.create_task(client.connect())

    try:
        # Wait until the first disconnect happens
        await asyncio.wait_for(first_disconnect_seen.wait(), timeout=5.0)
        # Wait until the second connection is established (reconnect)
        await asyncio.wait_for(second_connect_done.wait(), timeout=5.0)

        assert connect_count[0] >= 2, (
            f"Expected at least 2 connect attempts, got {connect_count[0]}"
        )
        assert client._reconnect_attempt > 0, (
            f"Reconnect attempt counter should be > 0, got {client._reconnect_attempt}"
        )
    finally:
        client._running = False
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, websockets.ConnectionClosed):
            pass


# ---------------------------------------------------------------------------
# SHARK CLIENT – OTHER ENDPOINTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_market_price(shark_client: SharkClient):
    """get_market_price returns ticker data for a symbol."""
    mock_response = {
        "symbol": "BTCUSDT",
        "lastPrice": "50000.00",
        "highPrice": "51000.00",
        "lowPrice": "49000.00",
    }
    shark_client._request = AsyncMock(return_value=mock_response)

    result = await shark_client.get_market_price("BTCUSDT")

    shark_client._request.assert_called_once_with("GET", "/v1/market/ticker24Hr/BTCUSDT")
    assert result["lastPrice"] == "50000.00"


@pytest.mark.asyncio
async def test_cancel_order(shark_client: SharkClient):
    """cancel_order sends a POST to delete-order."""
    mock_response = {"orderId": "cancel-111", "status": "CANCELLED"}
    shark_client._request = AsyncMock(return_value=mock_response)

    result = await shark_client.cancel_order(order_id="cancel-111", symbol="BTCUSDT")

    shark_client._request.assert_called_once()
    call_kwargs = shark_client._request.call_args[1]
    assert call_kwargs["json_body"]["orderId"] == "cancel-111"
    assert call_kwargs["json_body"]["symbol"] == "BTCUSDT"
    assert result["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_get_order_status(shark_client: SharkClient):
    """get_order_status sends a GET with query params."""
    mock_response = {"orderId": "status-222", "status": "FILLED"}
    shark_client._request = AsyncMock(return_value=mock_response)

    result = await shark_client.get_order_status(order_id="status-222")

    shark_client._request.assert_called_once()
    call_kwargs = shark_client._request.call_args[1]
    assert call_kwargs["params"]["orderId"] == "status-222"
    assert result["status"] == "FILLED"
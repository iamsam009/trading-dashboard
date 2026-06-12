"""
Shark Exchange REST Client

Async httpx-based client with:
- HMAC-SHA256 request signing (matching the official Shark Exchange protocol)
- Rate limiting (max 10 req/sec via sliding-window semaphore)
- Automatic retry with tenacity (exponential backoff on transient failures)
- Methods: get_account_balance, get_open_positions, place_order, cancel_order,
  get_order_status, get_market_price
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings

logger = logging.getLogger("trading_dashboard.shark_client")

# ── Rate Limiter ──────────────────────────────────────────────


class RateLimiter:
    """Sliding-window rate limiter (max `rate` requests per second)."""

    def __init__(self, rate: int = 10) -> None:
        self._rate = rate
        self._timestamps: list[float] = []

    async def acquire(self) -> None:
        """Block until a request slot is available."""
        import asyncio

        now = time.monotonic()
        # Remove timestamps older than 1 second
        self._timestamps = [t for t in self._timestamps if now - t < 1.0]

        if len(self._timestamps) >= self._rate:
            wait_time = 1.0 - (now - self._timestamps[0]) + 0.01
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            now = time.monotonic()
            self._timestamps = [t for t in self._timestamps if now - t < 1.0]

        self._timestamps.append(now)


# ── Shark Client ──────────────────────────────────────────────


class SharkClient:
    """
    Async client for Shark Exchange REST API.

    Usage:
        client = SharkClient(api_key="...", api_secret="...")
        balance = await client.get_account_balance()
        order = await client.place_order(symbol="BTCINR", side="BUY", ...)
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
        rate_limit: int = 10,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.shark_api_key
        self._api_secret = api_secret or settings.shark_api_secret
        self._base_url = (base_url or settings.shark_base_url).rstrip("/")
        self._rate_limiter = RateLimiter(rate=rate_limit)
        self._client: httpx.AsyncClient | None = None

    # ── Auth helpers ──────────────────────────────────────────

    @staticmethod
    def _generate_signature(secret: str, data: str) -> str:
        """HMAC-SHA256 hex digest."""
        return hmac.new(
            secret.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _timestamp() -> str:
        """Return current Unix timestamp in milliseconds."""
        return str(int(time.time() * 1000))

    def _signed_headers(
        self, method: str, query_string: str = "", body: str = ""
    ) -> dict[str, str]:
        """
        Build auth headers per Shark Exchange protocol.

        - GET:  sign the query string (including timestamp)
        - POST/PUT/DELETE: sign the JSON body
        """
        if method.upper() == "GET":
            data_to_sign = query_string
        else:
            data_to_sign = body

        sig = self._generate_signature(self._api_secret, data_to_sign)

        return {
            "api-key": self._api_key,
            "signature": sig,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── HTTP helpers ──────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create and return the httpx client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @retry(
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Send a signed request to the Shark Exchange API.

        Returns the parsed JSON response body.
        Raises httpx.HTTPStatusError on non-2xx responses.
        """
        await self._rate_limiter.acquire()

        client = await self._get_client()

        # Build query string with timestamp for GET requests
        ts = self._timestamp()
        if params is None:
            params = {}
        params["timestamp"] = ts

        query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        body_str = json.dumps(json_body, separators=(",", ":")) if json_body else ""
        headers = self._signed_headers(method, query_string, body_str)

        url = f"{self._base_url}{path}"

        logger.debug(
            "Shark API %s %s%s",
            method.upper(),
            url,
            f" {json_body}" if json_body else "",
        )

        if method.upper() == "GET":
            response = await client.get(
                f"{url}?{query_string}",
                headers=headers,
            )
        else:
            response = await client.request(
                method=method,
                url=f"{url}?{query_string}",
                headers=headers,
                content=body_str,
            )

        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    # ── Public API Methods ────────────────────────────────────

    async def get_account_balance(self) -> dict[str, Any]:
        """
        Fetch futures wallet balance.

        Returns raw exchange response containing wallet balances,
        available margin, unrealized PnL, etc.
        """
        return await self._request("GET", "/v1/wallet/futures-wallet/details")

    async def get_open_positions(self, symbol: str | None = None) -> dict[str, Any]:
        """
        Fetch open positions, optionally filtered by symbol.

        Returns raw exchange response with position data.
        """
        params: dict[str, Any] = {}
        if symbol:
            params["pair"] = symbol.upper()
        return await self._request("GET", "/v1/positions", params=params)

    async def place_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        leverage: int = 1,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Place a new order on Shark Exchange.

        Args:
            symbol: Trading pair (e.g. BTCINR)
            side: BUY or SELL
            order_type: MARKET, LIMIT, STOP_MARKET, STOP_LIMIT
            quantity: Order quantity in base asset
            price: Limit price (required for LIMIT, STOP_LIMIT)
            stop_price: Stop/trigger price (required for STOP_MARKET, STOP_LIMIT)
            leverage: Leverage multiplier
            reduce_only: If True, only reduces an existing position
            client_order_id: Custom client order ID

        Returns raw exchange order response.
        """
        body: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "orderType": order_type.upper(),
            "quantity": quantity,
            "leverage": leverage,
            "reduceOnly": reduce_only,
        }

        if price is not None:
            body["price"] = price
        if stop_price is not None:
            body["stopPrice"] = stop_price
        if client_order_id:
            body["clientOrderId"] = client_order_id

        return await self._request("POST", "/v1/order/place-order", json_body=body)

    async def cancel_order(
        self,
        order_id: str | None = None,
        client_order_id: str | None = None,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        """
        Cancel an existing order by exchange order_id or client_order_id.

        Args:
            order_id: Exchange-generated order ID
            client_order_id: Client-supplied order ID
            symbol: Trading pair (required if canceling by client_order_id)

        Returns raw exchange cancellation response.
        """
        body: dict[str, Any] = {}
        if order_id:
            body["orderId"] = order_id
        if client_order_id:
            body["clientOrderId"] = client_order_id
        if symbol:
            body["symbol"] = symbol.upper()

        return await self._request("POST", "/v1/order/delete-order", json_body=body)

    async def get_order_status(
        self,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetch the current status of an order.

        Args:
            order_id: Exchange-generated order ID
            client_order_id: Client-supplied order ID

        Returns raw exchange order details.
        """
        if order_id:
            return await self._request(
                "GET", "/v1/order/order-details", params={"orderId": order_id}
            )
        elif client_order_id:
            return await self._request(
                "GET",
                "/v1/order/order-details",
                params={"clientOrderId": client_order_id},
            )
        else:
            raise ValueError("Either order_id or client_order_id must be provided")

    async def get_market_price(self, symbol: str) -> dict[str, Any]:
        """
        Fetch the current 24hr ticker (including last price) for a symbol.

        Returns raw exchange ticker response.
        """
        return await self._request(
            "GET", f"/v1/market/ticker24Hr/{symbol.upper()}"
        )


# ── Module-level convenience ──────────────────────────────────

_shark_client: SharkClient | None = None


def get_shark_client() -> SharkClient:
    """Return a singleton SharkClient instance (configured from app settings)."""
    global _shark_client
    if _shark_client is None:
        _shark_client = SharkClient()
    return _shark_client
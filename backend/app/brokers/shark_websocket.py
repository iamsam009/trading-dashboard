"""
Shark Exchange WebSocket Client

Async WebSocket client that connects to the Shark Exchange real-time data stream.
- Subscribes to symbol tickers (24hr ticker, mark price updates)
- Automatic reconnection with exponential backoff
- Emits price updates to Redis pub/sub for downstream consumers
- Runs as a background task managed by the application lifespan

Shark Exchange uses Socket.IO for its streaming protocol. The flow is:
1. Obtain a listen-key via POST /v1/retail/listen-key
2. Connect to wss://fawss-uds.sharkexchange.in/auth-stream/{listenKey}
3. Receive real-time events (order updates, positions, ticker, etc.)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
import redis.asyncio as aioredis
import websockets

from app.config import get_settings

logger = logging.getLogger("trading_dashboard.shark_websocket")

# ── Constants ─────────────────────────────────────────────────

# How often to ping/refresh the listen key (Shark keys expire after 60 min)
LISTEN_KEY_REFRESH_INTERVAL = 30 * 60  # 30 minutes

# Maximum reconnect backoff
MAX_RECONNECT_BACKOFF = 60.0  # seconds

# Redis channel prefix for ticker events
TICKER_CHANNEL_PREFIX = "shark:ticker:"

# Redis channel for all raw events (for debugging / audit)
RAW_EVENTS_CHANNEL = "shark:events:raw"


class SharkWebSocketClient:
    """
    Async WebSocket client for Shark Exchange real-time data.

    Usage:
        client = SharkWebSocketClient()
        await client.subscribe(["BTCINR", "ETHINR"])
        await client.connect()
        # ... runs in background ...
        await client.disconnect()
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
        ws_url: str | None = None,
        redis_url: str | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.shark_api_key
        self._api_secret = api_secret or settings.shark_api_secret
        self._base_url = (base_url or settings.shark_base_url).rstrip("/")
        self._ws_base_url = (ws_url or settings.shark_ws_url).rstrip("/")
        self._redis_url = redis_url or settings.redis_url

        self._listen_key: str | None = None
        self._subscribed_symbols: set[str] = set()
        self._ws: Any = None  # websockets connection
        self._redis: aioredis.Redis | None = None
        self._running = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._reconnect_attempt = 0

    # ── Listen Key Management ─────────────────────────────────

    async def _get_listen_key(self) -> str:
        """
        Obtain a WebSocket listen key from the Shark REST API.

        Uses HMAC-SHA256 signed POST to /v1/retail/listen-key.
        """
        import hashlib
        import hmac

        ts = str(int(time.time() * 1000))
        qs = f"timestamp={ts}"

        sig = hmac.new(
            self._api_secret.encode("utf-8"),
            qs.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "api-key": self._api_key,
            "signature": sig,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.post(
                f"{self._base_url}/v1/retail/listen-key?{qs}",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        listen_key = data.get("listenKey") or data.get("data", {}).get("listenKey")
        if not listen_key:
            raise ValueError(f"Failed to obtain listen key: {data}")

        logger.info("Obtained Shark listen key: %s...", str(listen_key)[:20])
        return str(listen_key)

    async def _refresh_listen_key(self) -> None:
        """
        Periodically refresh (ping) the listen key to keep it alive.

        Shark listen keys expire after 60 minutes of inactivity.
        PUT /v1/retail/listen-key refreshes the expiry.
        """
        import hashlib
        import hmac

        while self._running and self._listen_key:
            await asyncio.sleep(LISTEN_KEY_REFRESH_INTERVAL)
            if not self._running or not self._listen_key:
                break

            try:
                ts = str(int(time.time() * 1000))
                qs = f"timestamp={ts}"
                sig = hmac.new(
                    self._api_secret.encode("utf-8"),
                    qs.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()

                headers = {
                    "api-key": self._api_key,
                    "signature": sig,
                    "Content-Type": "application/json",
                }

                async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                    resp = await client.put(
                        f"{self._base_url}/v1/retail/listen-key?{qs}",
                        headers=headers,
                    )
                    resp.raise_for_status()
                logger.debug("Shark listen key refreshed successfully")
            except Exception:
                logger.exception("Failed to refresh Shark listen key – will reconnect")

    # ── Redis Pub/Sub ─────────────────────────────────────────

    async def _ensure_redis(self) -> aioredis.Redis:
        """Lazily connect to Redis."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info("Redis connected for Shark WebSocket events")
        return self._redis

    async def _publish_ticker(self, symbol: str, data: dict[str, Any]) -> None:
        """Publish a ticker update to Redis pub/sub."""
        try:
            redis = await self._ensure_redis()
            channel = f"{TICKER_CHANNEL_PREFIX}{symbol.lower()}"
            payload = json.dumps(data)
            await redis.publish(channel, payload)
        except Exception:
            logger.exception("Failed to publish ticker for %s", symbol)

    async def _publish_raw_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish raw event to Redis for audit/debugging."""
        try:
            redis = await self._ensure_redis()
            payload = json.dumps({"type": event_type, "data": data, "ts": time.time()})
            await redis.publish(RAW_EVENTS_CHANNEL, payload)
        except Exception:
            logger.exception("Failed to publish raw event")

    # ── WebSocket Connection ──────────────────────────────────

    async def _connect_ws(self) -> None:
        """
        Connect to the Shark Exchange WebSocket stream.

        Uses the `websockets` library to connect to the auth-stream endpoint.
        Receives events and dispatches to handlers.
        """
        ws_url = f"{self._ws_base_url}/auth-stream/{self._listen_key}"
        logger.info("Connecting to Shark WebSocket: %s", ws_url)

        try:
            self._ws = await websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=10,
                max_size=2**20,  # 1MB max message size
            )
            self._reconnect_attempt = 0  # Reset on successful connection
            logger.info("✅ Connected to Shark WebSocket stream")

            # Start receiving messages
            await self._receive_loop()
        except Exception:
            logger.exception("WebSocket connection failed")
            raise

    async def _receive_loop(self) -> None:
        """Continuously receive and dispatch WebSocket messages."""
        while self._running and self._ws is not None:
            try:
                message = await self._ws.recv()
                await self._handle_message(message)
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning("WebSocket connection closed: %s (code=%s)", e.reason, e.code)
                break
            except Exception:
                logger.exception("Error in WebSocket receive loop")
                break

    async def _handle_message(self, raw_message: str) -> None:
        """
        Parse and dispatch an incoming WebSocket message.

        Shark Exchange sends events like:
        - ticker updates
        - order status updates
        - position updates
        - account balance updates
        """
        try:
            # Shark Exchange may send Socket.IO framed messages or plain JSON
            # Try to parse as JSON first
            data: dict[str, Any] = json.loads(raw_message)

            # Log raw event for audit
            await self._publish_raw_event(data.get("e", "unknown"), data)

            event_type = data.get("e", "")

            if event_type == "24hrTicker":
                symbol = data.get("s", "")
                if symbol:
                    await self._publish_ticker(symbol, {
                        "symbol": symbol,
                        "price": data.get("c", "0"),  # Last price
                        "price_change": data.get("p", "0"),
                        "price_change_percent": data.get("P", "0"),
                        "high": data.get("h", "0"),
                        "low": data.get("l", "0"),
                        "volume": data.get("v", "0"),
                        "timestamp": data.get("E", int(time.time() * 1000)),
                    })
            elif event_type == "markPriceUpdate":
                symbol = data.get("s", "")
                if symbol:
                    await self._publish_ticker(symbol, {
                        "symbol": symbol,
                        "mark_price": data.get("p", "0"),
                        "index_price": data.get("i", "0"),
                        "funding_rate": data.get("r", "0"),
                        "timestamp": data.get("E", int(time.time() * 1000)),
                    })
            elif event_type == "ACCOUNT_UPDATE":
                # Account/balance updates
                logger.debug("Account update received: %s", json.dumps(data, default=str)[:200])
            elif event_type == "ORDER_TRADE_UPDATE":
                # Order fill / status update
                logger.debug("Order update received: %s", json.dumps(data, default=str)[:200])
            else:
                logger.debug("Unknown event type '%s': %s", event_type, raw_message[:200])

        except json.JSONDecodeError:
            # May be Socket.IO control frames (e.g., '2' for ping, '3' for pong)
            logger.debug("Non-JSON WebSocket message: %s", raw_message[:100])

    # ── Public API ────────────────────────────────────────────

    def subscribe(self, symbols: list[str]) -> None:
        """
        Register symbols to track.

        In the current Shark Exchange WebSocket implementation, all events
        for the authenticated user are streamed automatically (no explicit
        subscription needed). This method is kept for future use when
        symbol-level subscription is supported.
        """
        self._subscribed_symbols.update(s.upper() for s in symbols)
        logger.info("Tracking symbols: %s", self._subscribed_symbols)

    async def connect(self) -> None:
        """
        Start the WebSocket connection with automatic reconnection.

        This method blocks until disconnect() is called.
        """
        self._running = True

        while self._running:
            try:
                # Obtain or refresh listen key
                if not self._listen_key:
                    self._listen_key = await self._get_listen_key()

                # Start the listen key refresh task
                refresh_task = asyncio.create_task(self._refresh_listen_key())
                self._tasks.append(refresh_task)

                # Connect and receive events
                await self._connect_ws()

            except Exception:
                self._reconnect_attempt += 1
                backoff = min(
                    MAX_RECONNECT_BACKOFF,
                    2 ** min(self._reconnect_attempt, 6),
                )
                logger.warning(
                    "Shark WebSocket reconnect attempt %d in %.1fs",
                    self._reconnect_attempt,
                    backoff,
                )
                # Invalidate listen key on connection failure
                self._listen_key = None
                await asyncio.sleep(backoff)

    async def disconnect(self) -> None:
        """Gracefully disconnect from the WebSocket and clean up resources."""
        self._running = False

        # Cancel background tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self._tasks.clear()

        # Close WebSocket
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        # Close Redis
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None

        logger.info("Shark WebSocket client disconnected")


# ── Module-level convenience ──────────────────────────────────

_shark_ws_client: SharkWebSocketClient | None = None


def get_shark_ws_client() -> SharkWebSocketClient:
    """Return a singleton SharkWebSocketClient instance."""
    global _shark_ws_client
    if _shark_ws_client is None:
        _shark_ws_client = SharkWebSocketClient()
    return _shark_ws_client
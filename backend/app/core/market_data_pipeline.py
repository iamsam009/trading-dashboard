"""
Market Data Pipeline – background task that bridges Shark WebSocket → Redis → Strategy Engines.

Flow:
  1. Subscribes to Shark Exchange WebSocket (via SharkWebSocketClient)
  2. Receives raw ticker events, normalizes them into a ``MarketTick``
  3. Aggregates ticks into 1-second OHLCV candles (configurable period)
  4. Publishes candles to Redis pub/sub channels:
     - ``market:candle:{symbol}`` for strategy engines
     - ``market:price:{symbol}`` for frontend price updates
  5. Also pushes to the ConnectionManager for direct WebSocket broadcast

Strategy engines subscribe to Redis channels and pull candles as they arrive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.config import get_settings
from app.engine.strategy_engine import MarketTick

logger = logging.getLogger("trading_dashboard.market_data")

# ── Constants ─────────────────────────────────────────────────────────
CANDLE_INTERVAL = 1.0  # seconds – aggregate ticks into 1s candles
MAX_CANDLE_AGE = 5.0   # seconds – flush stale partial candles

# Redis channel prefixes
CANDLE_CHANNEL_PREFIX = "market:candle:"
PRICE_CHANNEL_PREFIX = "market:price:"


class MarketDataPipeline:
    """
    Background task that consumes raw Shark ticker data and distributes
    aggregated candles to all interested consumers.

    Usage::

        pipeline = MarketDataPipeline()
        await pipeline.start()
        # … runs forever …
        await pipeline.stop()
    """

    def __init__(
        self,
        redis_url: str | None = None,
    ) -> None:
        settings = get_settings()
        self._redis_url = redis_url or settings.redis_url
        self._redis: aioredis.Redis | None = None
        self._running = False
        self._tasks: list[asyncio.Task[Any]] = []

        # Per-symbol: accumulating candle [(timestamp, price, volume), ...]
        self._tick_buffers: dict[str, list[tuple[float, float, float]]] = {}
        self._last_flush: dict[str, float] = {}

    # ── Public API ────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch the pipeline (connects Redis, starts the aggregation loop)."""
        self._running = True
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        await self._redis.ping()
        logger.info("Market data pipeline started (Redis connected)")

        self._tasks.append(asyncio.ensure_future(self._aggregation_loop()))

    async def stop(self) -> None:
        """Gracefully stop the pipeline."""
        self._running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self._tasks.clear()

        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

        logger.info("Market data pipeline stopped")

    async def ingest_ticker(self, raw: dict[str, Any]) -> None:
        """Accept a raw ticker event from Shark WebSocket and buffer it.

        Called by the SharkWebSocketClient's ``_handle_message`` or
        by a Redis subscriber bridge.

        Expected raw format (from Shark)::

            {
                "e": "24hrTicker",      // event type
                "s": "BTCINR",          // symbol
                "c": "4200000.00",      // close / last price
                "h": "4250000.00",      // 24h high
                "l": "4150000.00",      // 24h low
                "v": "125.43",          // 24h volume
                "P": "2.5"              // 24h price change percent
            }
        """
        event_type = raw.get("e", "")
        symbol = raw.get("s", "")
        if not symbol:
            return

        if event_type == "24hrTicker":
            try:
                price = float(raw.get("c", 0))
                volume = float(raw.get("v", 0))
            except (ValueError, TypeError):
                return

            # Buffer the tick
            ts = time.time()
            self._tick_buffers.setdefault(symbol, []).append((ts, price, volume))

            # Publish real-time price to Redis
            try:
                await self._publish_price(symbol, {
                    "symbol": symbol,
                    "price": price,
                    "high_24h": float(raw.get("h", 0)),
                    "low_24h": float(raw.get("l", 0)),
                    "volume_24h": volume,
                    "change_percent": float(raw.get("P", 0)),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                logger.exception("Failed to publish price for %s", symbol)

    async def _publish_price(self, symbol: str, data: dict[str, Any]) -> None:
        """Publish a price update to Redis."""
        if self._redis is None:
            return
        channel = f"{PRICE_CHANNEL_PREFIX}{symbol.lower()}"
        await self._redis.publish(channel, json.dumps(data))

    async def _publish_candle(self, symbol: str, candle: dict[str, Any]) -> None:
        """Publish an aggregated candle to Redis."""
        if self._redis is None:
            return
        channel = f"{CANDLE_CHANNEL_PREFIX}{symbol.lower()}"
        await self._redis.publish(channel, json.dumps(candle))

    # ── Aggregation Loop ──────────────────────────────────────────────

    async def _aggregation_loop(self) -> None:
        """Periodically flush tick buffers into OHLCV candles."""
        while self._running:
            try:
                now = time.time()
                to_flush: list[str] = []

                for symbol, ticks in list(self._tick_buffers.items()):
                    if not ticks:
                        continue

                    # Flush if candle interval elapsed or buffer is stale
                    oldest_ts = ticks[0][0]
                    if (now - oldest_ts >= CANDLE_INTERVAL) or (
                        now - self._last_flush.get(symbol, now) >= MAX_CANDLE_AGE
                    ):
                        to_flush.append(symbol)

                for symbol in to_flush:
                    await self._flush_candle(symbol)

                # Also flush any stale buffers
                for symbol, ticks in list(self._tick_buffers.items()):
                    if ticks and (now - ticks[0][0] >= MAX_CANDLE_AGE):
                        if symbol not in to_flush:
                            await self._flush_candle(symbol)

                await asyncio.sleep(0.1)  # 100ms polling interval
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in aggregation loop")
                await asyncio.sleep(1.0)

    async def _flush_candle(self, symbol: str) -> None:
        """Aggregate buffered ticks for a symbol into an OHLCV candle."""
        ticks = self._tick_buffers.pop(symbol, [])
        if not ticks:
            return

        prices = [t[1] for t in ticks]
        volumes = [t[2] for t in ticks]
        timestamps = [t[0] for t in ticks]

        candle = {
            "symbol": symbol,
            "timestamp": datetime.fromtimestamp(timestamps[0], tz=timezone.utc).isoformat(),
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": sum(volumes),
            "tick_count": len(ticks),
        }

        self._last_flush[symbol] = time.time()

        try:
            await self._publish_candle(symbol, candle)
        except Exception:
            logger.exception("Failed to publish candle for %s", symbol)

    async def _broadcast_via_manager(self, event_type: str, data: dict[str, Any]) -> None:
        """Push to the ConnectionManager for direct WebSocket broadcast.

        This is a convenience bridge – the WebSocket endpoint can also
        subscribe to Redis directly for multi-instance deployments.
        """
        try:
            from app.websocket.manager import get_ws_manager

            manager = get_ws_manager()
            symbol = data.get("symbol")
            await manager.broadcast(event_type, data, symbol=symbol)
        except Exception:
            logger.exception("Failed to broadcast via ConnectionManager")


# ── Module-level convenience ──────────────────────────────────────────

_pipeline: MarketDataPipeline | None = None


def get_market_data_pipeline() -> MarketDataPipeline:
    """Return the application-wide MarketDataPipeline singleton."""
    global _pipeline
    if _pipeline is None:
        _pipeline = MarketDataPipeline()
    return _pipeline
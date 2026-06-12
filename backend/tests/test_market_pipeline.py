"""
Tests for the Market Data Pipeline – tick ingestion, candle aggregation,
Redis pub/sub publishing, and ConnectionManager broadcast.

Covers:
- Tick → 1s OHLCV candle aggregation
- Redis pub/sub channel verification
- Buffer flushing on interval and staleness
- Broadcast to ConnectionManager
- Pipeline lifecycle (start/stop)
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ticker(symbol: str = "BTCINR", price: float = 50000.0, volume: float = 10.0,
                 high: float = 51000.0, low: float = 49000.0, change_pct: float = 2.5) -> dict:
    """Build a Shark 24hrTicker event dict."""
    return {
        "e": "24hrTicker",
        "s": symbol,
        "c": str(price),
        "h": str(high),
        "l": str(low),
        "v": str(volume),
        "P": str(change_pct),
    }


# ---------------------------------------------------------------------------
# Pipeline Tests
# ---------------------------------------------------------------------------

class TestTickIngestion:
    """Unit tests for tick buffering and price publishing."""

    @pytest.mark.asyncio
    async def test_ingest_ticker_buffers_data(self, mock_redis: AsyncMock):
        """Raw 24hrTicker events are buffered into per-symbol tick lists."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis

        ticker = _make_ticker("BTCINR", price=50000.0, volume=1.0)
        await pipeline.ingest_ticker(ticker)

        assert "BTCINR" in pipeline._tick_buffers
        assert len(pipeline._tick_buffers["BTCINR"]) == 1

        ts, price, vol = pipeline._tick_buffers["BTCINR"][0]
        assert price == 50000.0
        assert vol == 1.0

    @pytest.mark.asyncio
    async def test_ingest_ticker_ignores_unknown_event_type(self, mock_redis: AsyncMock):
        """Non-24hrTicker events are silently ignored."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis

        await pipeline.ingest_ticker({"e": "trade", "s": "BTCINR", "p": "50000"})

        assert "BTCINR" not in pipeline._tick_buffers

    @pytest.mark.asyncio
    async def test_ingest_ticker_ignores_missing_symbol(self, mock_redis: AsyncMock):
        """Events without a symbol are ignored."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis

        await pipeline.ingest_ticker({"e": "24hrTicker", "c": "50000"})

        assert len(pipeline._tick_buffers) == 0

    @pytest.mark.asyncio
    async def test_ingest_ticker_publishes_price_to_redis(self, mock_redis: AsyncMock):
        """Each ticker publishes a price update to Redis market:price:{symbol}."""
        from app.core.market_data_pipeline import MarketDataPipeline, PRICE_CHANNEL_PREFIX

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis
        mock_redis.publish = AsyncMock()

        ticker = _make_ticker("ETHINR", price=200000.0, volume=5.0)
        await pipeline.ingest_ticker(ticker)

        mock_redis.publish.assert_called()
        call_args = mock_redis.publish.call_args
        channel = call_args[0][0]
        assert channel == f"{PRICE_CHANNEL_PREFIX}ethinr"

        payload = json.loads(call_args[0][1])
        assert payload["symbol"] == "ETHINR"
        assert payload["price"] == 200000.0
        assert payload["volume_24h"] == 5.0
        assert payload["high_24h"] == 51000.0
        assert payload["low_24h"] == 49000.0
        assert payload["change_percent"] == 2.5
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_ingest_ticker_handles_redis_failure_gracefully(self, mock_redis: AsyncMock):
        """Redis publish failure does not crash the pipeline."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis
        mock_redis.publish = AsyncMock(side_effect=RuntimeError("Redis down"))

        ticker = _make_ticker("BTCINR", price=50000.0)
        # Should not raise
        await pipeline.ingest_ticker(ticker)

        assert len(pipeline._tick_buffers["BTCINR"]) == 1

    @pytest.mark.asyncio
    async def test_multiple_symbols_buffered_separately(self, mock_redis: AsyncMock):
        """Ticks for different symbols are buffered independently."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis
        mock_redis.publish = AsyncMock()

        await pipeline.ingest_ticker(_make_ticker("BTCINR", price=50000.0))
        await pipeline.ingest_ticker(_make_ticker("ETHINR", price=200000.0))
        await pipeline.ingest_ticker(_make_ticker("BTCINR", price=50100.0))

        assert len(pipeline._tick_buffers["BTCINR"]) == 2
        assert len(pipeline._tick_buffers["ETHINR"]) == 1


class TestCandleAggregation:
    """Tests for tick → OHLCV candle aggregation."""

    @pytest.mark.asyncio
    async def test_flush_candle_generates_correct_ohlcv(self, mock_redis: AsyncMock):
        """Buffered ticks produce OHLCV with correct open/high/low/close/volume."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis
        mock_redis.publish = AsyncMock()

        # Buffer ticks with known prices
        now = time.time()
        pipeline._tick_buffers["BTCINR"] = [
            (now, 50000.0, 1.0),
            (now + 0.1, 50100.0, 2.0),
            (now + 0.2, 49900.0, 1.5),
            (now + 0.3, 50050.0, 0.5),
        ]

        await pipeline._flush_candle("BTCINR")

        # Buffer should be consumed
        assert "BTCINR" not in pipeline._tick_buffers

        # Verify the candle published to Redis
        mock_redis.publish.assert_called()
        channel = mock_redis.publish.call_args[0][0]
        assert channel == "market:candle:btcinr"

        candle = json.loads(mock_redis.publish.call_args[0][1])
        assert candle["symbol"] == "BTCINR"
        assert candle["open"] == 50000.0
        assert candle["high"] == 50100.0
        assert candle["low"] == 49900.0
        assert candle["close"] == 50050.0
        assert candle["volume"] == 5.0  # 1.0 + 2.0 + 1.5 + 0.5
        assert candle["tick_count"] == 4
        assert "timestamp" in candle

    @pytest.mark.asyncio
    async def test_flush_candle_handles_empty_buffer(self, mock_redis: AsyncMock):
        """Flushing an empty buffer is a no-op."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis
        mock_redis.publish = AsyncMock()

        await pipeline._flush_candle("NONEXISTENT")

        mock_redis.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_candle_single_tick(self, mock_redis: AsyncMock):
        """A single tick produces a candle where open=high=low=close."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis
        mock_redis.publish = AsyncMock()

        pipeline._tick_buffers["BTCINR"] = [(time.time(), 50000.0, 0.5)]

        await pipeline._flush_candle("BTCINR")

        candle = json.loads(mock_redis.publish.call_args[0][1])
        assert candle["open"] == candle["high"] == candle["low"] == candle["close"] == 50000.0
        assert candle["volume"] == 0.5
        assert candle["tick_count"] == 1


class TestAggregationLoop:
    """Tests for the background aggregation loop."""

    @pytest.mark.asyncio
    async def test_aggregation_loop_flushes_after_interval(self, mock_redis: AsyncMock):
        """Loop flushes buffers once CANDLE_INTERVAL has elapsed since oldest tick."""
        from app.core.market_data_pipeline import MarketDataPipeline, CANDLE_INTERVAL

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis
        mock_redis.publish = AsyncMock()

        # Add a tick with a timestamp in the past (beyond CANDLE_INTERVAL)
        past = time.time() - CANDLE_INTERVAL - 0.5
        pipeline._tick_buffers["BTCINR"] = [(past, 50000.0, 1.0)]
        pipeline._running = True

        # Run one iteration of the loop
        loop_task = asyncio.ensure_future(pipeline._aggregation_loop())
        await asyncio.sleep(0.2)  # Let one iteration complete
        pipeline._running = False
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # Buffer should be flushed
        assert "BTCINR" not in pipeline._tick_buffers
        mock_redis.publish.assert_called()

    @pytest.mark.asyncio
    async def test_aggregation_loop_flushes_stale_buffers(self, mock_redis: AsyncMock):
        """Stale buffers (> MAX_CANDLE_AGE) are flushed even if interval not met."""
        from app.core.market_data_pipeline import MarketDataPipeline, MAX_CANDLE_AGE

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis
        mock_redis.publish = AsyncMock()

        # Add a tick older than MAX_CANDLE_AGE
        very_old = time.time() - MAX_CANDLE_AGE - 1.0
        pipeline._tick_buffers["ETHINR"] = [(very_old, 200000.0, 2.0)]
        pipeline._running = True

        loop_task = asyncio.ensure_future(pipeline._aggregation_loop())
        await asyncio.sleep(0.2)
        pipeline._running = False
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        assert "ETHINR" not in pipeline._tick_buffers

    @pytest.mark.asyncio
    async def test_aggregation_loop_does_not_flush_recent_ticks(self, mock_redis: AsyncMock):
        """Ticks newer than CANDLE_INTERVAL are NOT flushed."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis
        mock_redis.publish = AsyncMock()

        # Add a very recent tick
        now = time.time()
        pipeline._tick_buffers["BTCINR"] = [(now, 50000.0, 1.0)]
        pipeline._running = True

        loop_task = asyncio.ensure_future(pipeline._aggregation_loop())
        await asyncio.sleep(0.2)
        pipeline._running = False
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # Recent tick should still be buffered
        assert "BTCINR" in pipeline._tick_buffers
        assert len(pipeline._tick_buffers["BTCINR"]) == 1


class TestBroadcastToManager:
    """Tests for the ConnectionManager broadcast bridge."""

    @pytest.mark.asyncio
    async def test_broadcast_via_manager(self, mock_redis: AsyncMock, monkeypatch):
        """_broadcast_via_manager pushes market data to ConnectionManager."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis

        mock_broadcast = AsyncMock()
        mock_manager = AsyncMock()
        mock_manager.broadcast = mock_broadcast
        monkeypatch.setattr(
            "app.websocket.manager.get_ws_manager",
            lambda: mock_manager,
        )

        await pipeline._broadcast_via_manager(
            "market_price", {"symbol": "BTCINR", "price": 50000.0}
        )

        mock_broadcast.assert_called_once_with(
            "market_price", {"symbol": "BTCINR", "price": 50000.0}, symbol="BTCINR"
        )

    @pytest.mark.asyncio
    async def test_broadcast_via_manager_handles_errors(self, mock_redis: AsyncMock, monkeypatch):
        """Broadcast failure does not crash the pipeline."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis

        mock_manager = AsyncMock()
        mock_manager.broadcast = AsyncMock(side_effect=RuntimeError("WS down"))
        monkeypatch.setattr(
            "app.websocket.manager.get_ws_manager",
            lambda: mock_manager,
        )

        # Should not raise
        await pipeline._broadcast_via_manager(
            "market_price", {"symbol": "BTCINR", "price": 50000.0}
        )


class TestPipelineLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_connects_redis_and_starts_loop(self, mock_redis: AsyncMock):
        """start() pings Redis and creates the aggregation loop task."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        with patch("app.core.market_data_pipeline.aioredis") as mock_aioredis:
            mock_aioredis.from_url = MagicMock(return_value=mock_redis)
            await pipeline.start()

        mock_redis.ping.assert_called_once()
        assert len(pipeline._tasks) == 1
        assert pipeline._running is True

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks_and_closes_redis(self, mock_redis: AsyncMock):
        """stop() cancels background tasks and closes the Redis connection."""
        from app.core.market_data_pipeline import MarketDataPipeline

        pipeline = MarketDataPipeline()
        pipeline._redis = mock_redis
        pipeline._running = True

        # Create a dummy task
        async def _dummy():
            while True:
                await asyncio.sleep(0.1)

        pipeline._tasks = [asyncio.ensure_future(_dummy())]

        await pipeline.stop()

        assert pipeline._running is False
        assert len(pipeline._tasks) == 0
        mock_redis.aclose.assert_called_once()
        assert pipeline._redis is None


class TestSingletonAccessor:
    """Tests for the module-level singleton getter."""

    def test_get_market_data_pipeline_returns_singleton(self):
        """get_market_data_pipeline() returns the same instance."""
        from app.core.market_data_pipeline import (
            MarketDataPipeline,
            get_market_data_pipeline,
        )

        # Reset singleton for test isolation
        import app.core.market_data_pipeline as mp

        mp._pipeline = None

        p1 = get_market_data_pipeline()
        p2 = get_market_data_pipeline()

        assert p1 is p2
        assert isinstance(p1, MarketDataPipeline)

        # Clean up
        mp._pipeline = None
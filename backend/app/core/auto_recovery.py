"""
Auto-Recovery Module for Shark WebSocket

Provides heartbeat monitoring and automatic reconnection logic for the
Shark WebSocket connection. Detects stale connections when no heartbeat
is received within the expected interval, then triggers reconnection.

Also handles:
- Database disconnect retry logic (with exponential backoff)
- Redis disconnect retry logic
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger("trading_dashboard.auto_recovery")

# ── Constants ────────────────────────────────────────────────
HEARTBEAT_INTERVAL_SECONDS = 30        # Expected heartbeat interval
HEARTBEAT_MISS_THRESHOLD = 3           # Miss this many before reconnecting
RECONNECT_INITIAL_DELAY = 1.0          # Initial reconnect delay (seconds)
RECONNECT_MAX_DELAY = 60.0             # Max reconnect delay (seconds)
RECONNECT_BACKOFF_FACTOR = 2.0         # Exponential backoff multiplier
DB_RETRY_MAX_ATTEMPTS = 5              # Max DB connection retries
DB_RETRY_INITIAL_DELAY = 0.5           # Initial DB retry delay (seconds)
REDIS_RETRY_MAX_ATTEMPTS = 5           # Max Redis connection retries


@dataclass
class HeartbeatMonitor:
    """
    Monitors WebSocket heartbeat signals.

    Tracks the last time a heartbeat was received.  If the gap exceeds
    HEARTBEAT_INTERVAL_SECONDS * HEARTBEAT_MISS_THRESHOLD, the connection
    is considered stale.
    """

    last_heartbeat: float = field(default_factory=time.monotonic)
    miss_count: int = 0
    _callback: Callable[[], Awaitable[None]] | None = field(default=None, repr=False)

    def record_heartbeat(self) -> None:
        """Record a received heartbeat, resetting the miss counter."""
        self.last_heartbeat = time.monotonic()
        self.miss_count = 0

    def record_message(self) -> None:
        """
        Record any incoming message — extends the effective heartbeat window
        without resetting the miss counter (only explicit heartbeats do that).
        """
        # Any message is a sign of life; update the timestamp but don't reset count
        self.last_heartbeat = time.monotonic()

    @property
    def is_stale(self) -> bool:
        """Returns True if the connection is considered stale."""
        elapsed = time.monotonic() - self.last_heartbeat
        return elapsed > (HEARTBEAT_INTERVAL_SECONDS * HEARTBEAT_MISS_THRESHOLD)

    @property
    def seconds_since_last_heartbeat(self) -> float:
        """Seconds since the last heartbeat was received."""
        return time.monotonic() - self.last_heartbeat

    def set_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Set the async callback to invoke when the connection is stale."""
        self._callback = callback

    async def trigger_reconnect(self) -> None:
        """Trigger the reconnect callback if set."""
        if self._callback is not None:
            await self._callback()


class ReconnectController:
    """
    Manages exponential backoff reconnection with jitter.

    Usage:
        ctrl = ReconnectController()
        while True:
            try:
                await connect()
                ctrl.reset()
            except Exception:
                delay = ctrl.next_delay()
                await asyncio.sleep(delay)
    """

    def __init__(
        self,
        initial_delay: float = RECONNECT_INITIAL_DELAY,
        max_delay: float = RECONNECT_MAX_DELAY,
        backoff_factor: float = RECONNECT_BACKOFF_FACTOR,
    ) -> None:
        self._initial_delay = initial_delay
        self._max_delay = max_delay
        self._backoff_factor = backoff_factor
        self._attempt: int = 0

    def reset(self) -> None:
        """Reset the reconnect attempt counter."""
        self._attempt = 0

    def next_delay(self) -> float:
        """
        Calculate the next delay with exponential backoff and jitter.

        Returns seconds to wait before the next reconnect attempt.
        """
        import random

        self._attempt += 1
        delay = self._initial_delay * (self._backoff_factor ** (self._attempt - 1))
        delay = min(delay, self._max_delay)
        # Add jitter: ±25%
        jitter = delay * 0.25 * (2 * random.random() - 1)
        return delay + jitter

    @property
    def attempt(self) -> int:
        """Current reconnect attempt number."""
        return self._attempt


async def retry_db_operation(
    operation: Callable[[], Awaitable],
    max_attempts: int = DB_RETRY_MAX_ATTEMPTS,
    initial_delay: float = DB_RETRY_INITIAL_DELAY,
) -> None:
    """
    Retry a database operation with exponential backoff.

    Raises the last exception if all attempts are exhausted.
    """
    from app.core.metrics import record_db_error

    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            await operation()
            return  # Success
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "DB operation failed (attempt %d/%d): %s",
                attempt,
                max_attempts,
                exc,
            )

            if attempt < max_attempts:
                delay = initial_delay * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

    record_db_error()
    logger.error("DB operation failed after %d attempts", max_attempts)
    if last_exc:
        raise last_exc


async def retry_redis_operation(
    operation: Callable[[], Awaitable],
    max_attempts: int = REDIS_RETRY_MAX_ATTEMPTS,
    initial_delay: float = DB_RETRY_INITIAL_DELAY,
) -> None:
    """
    Retry a Redis operation with exponential backoff.

    Raises the last exception if all attempts are exhausted.
    """
    from app.core.metrics import record_redis_error

    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            await operation()
            return
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Redis operation failed (attempt %d/%d): %s",
                attempt,
                max_attempts,
                exc,
            )

            if attempt < max_attempts:
                delay = initial_delay * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

    record_redis_error()
    logger.error("Redis operation failed after %d attempts", max_attempts)
    if last_exc:
        raise last_exc


async def run_heartbeat_monitor(
    monitor: HeartbeatMonitor,
    check_interval: float = 5.0,
) -> None:
    """
    Background task that periodically checks heartbeat health.

    If the connection is stale, triggers the reconnect callback.
    Runs forever until the task is cancelled.
    """
    logger.info(
        "Heartbeat monitor started (interval=%ss, threshold=%s misses)",
        check_interval,
        HEARTBEAT_MISS_THRESHOLD,
    )
    try:
        while True:
            await asyncio.sleep(check_interval)
            if monitor.is_stale:
                logger.warning(
                    "WebSocket heartbeat stale – last heartbeat %.1fs ago (threshold: %.1fs). "
                    "Triggering reconnection.",
                    monitor.seconds_since_last_heartbeat,
                    HEARTBEAT_INTERVAL_SECONDS * HEARTBEAT_MISS_THRESHOLD,
                )
                await monitor.trigger_reconnect()
    except asyncio.CancelledError:
        logger.info("Heartbeat monitor cancelled")
        raise
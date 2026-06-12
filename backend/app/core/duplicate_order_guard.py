"""
Duplicate Order Prevention Guard

Prevents duplicate orders by tracking in-flight client_order_id values
and recently placed orders within a configurable time window.

Uses Redis for distributed deduplication across multiple backend instances.
"""

from __future__ import annotations

import hashlib
import logging

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger("trading_dashboard.duplicate_guard")

# ── Constants ────────────────────────────────────────────────
DUPLICATE_WINDOW_SECONDS = 30  # How long to remember a placed order
REDIS_KEY_PREFIX = "dedup:order:"  # Redis key prefix for dedup entries


class DuplicateOrderError(Exception):
    """Raised when a duplicate order is detected."""


class DuplicateOrderGuard:
    """
    Prevents duplicate orders using Redis-backed deduplication.

    An order is considered a duplicate if:
    - The same client_order_id has been placed within the dedup window
    - OR the same (user_id, symbol, side, quantity, price, order_type) tuple
      was placed within the dedup window (fallback when no client_order_id)

    Usage:
        guard = DuplicateOrderGuard()
        await guard.check_or_raise(user_id, request)
        # ... place order ...
        await guard.record(user_id, request, exchange_response)
    """

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._redis: aioredis.Redis | None = redis_client

    async def _get_redis(self) -> aioredis.Redis:
        """Lazily initialize Redis connection."""
        if self._redis is None:
            settings = get_settings()
            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
        return self._redis

    # ── Hash helpers ──────────────────────────────────────────

    @staticmethod
    def _build_order_hash(
        user_id: int,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None,
        order_type: str,
    ) -> str:
        """Build a deterministic hash for deduplication."""
        raw = f"{user_id}:{symbol}:{side}:{quantity}:{price}:{order_type}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _client_order_key(user_id: int, client_order_id: str) -> str:
        """Redis key for a client_order_id dedup entry."""
        return f"{REDIS_KEY_PREFIX}client:{user_id}:{client_order_id}"

    @staticmethod
    def _order_hash_key(order_hash: str) -> str:
        """Redis key for an order-hash dedup entry."""
        return f"{REDIS_KEY_PREFIX}hash:{order_hash}"

    # ── Public API ────────────────────────────────────────────

    async def check_or_raise(
        self,
        user_id: int,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None,
        order_type: str,
        client_order_id: str | None = None,
    ) -> None:
        """
        Check if this order is a duplicate.  Raises DuplicateOrderError if so.

        Checks both:
        1. client_order_id (if provided) — exact match
        2. order hash — content-based match (fallback)
        """
        redis = await self._get_redis()

        # Check 1: client_order_id exact match
        if client_order_id:
            key = self._client_order_key(user_id, client_order_id)
            existing = await redis.get(key)
            if existing is not None:
                logger.warning(
                    "Duplicate order detected by client_order_id: user=%d, client_id=%s, "
                    "existing=%s",
                    user_id,
                    client_order_id,
                    existing,
                )
                raise DuplicateOrderError(
                    f"Duplicate order: client_order_id '{client_order_id}' "
                    f"was already used within the last {DUPLICATE_WINDOW_SECONDS}s"
                )

        # Check 2: Content hash match
        order_hash = self._build_order_hash(user_id, symbol, side, quantity, price, order_type)
        hash_key = self._order_hash_key(order_hash)
        existing_hash = await redis.get(hash_key)
        if existing_hash is not None:
            logger.warning(
                "Duplicate order detected by content hash: user=%d, hash=%s",
                user_id,
                order_hash,
            )
            raise DuplicateOrderError(
                f"Duplicate order: an identical order was placed within "
                f"the last {DUPLICATE_WINDOW_SECONDS}s"
            )

    async def record(
        self,
        user_id: int,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None,
        order_type: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> None:
        """
        Record an order in the dedup cache after successful placement.

        Stores both the client_order_id key and the content hash key
        with a TTL of DUPLICATE_WINDOW_SECONDS.
        """
        redis = await self._get_redis()
        payload = f"{symbol}|{side}|{quantity}|{exchange_order_id or 'N/A'}"

        pipe = redis.pipeline()

        if client_order_id:
            pipe.setex(
                self._client_order_key(user_id, client_order_id),
                DUPLICATE_WINDOW_SECONDS,
                payload,
            )

        order_hash = self._build_order_hash(user_id, symbol, side, quantity, price, order_type)
        pipe.setex(
            self._order_hash_key(order_hash),
            DUPLICATE_WINDOW_SECONDS,
            payload,
        )

        await pipe.execute()
        logger.debug(
            "Dedup recorded: user=%d, symbol=%s, side=%s, qty=%s, exchange_id=%s",
            user_id,
            symbol,
            side,
            quantity,
            exchange_order_id,
        )

    async def clear(self, user_id: int, client_order_id: str | None = None) -> None:
        """
        Manually clear dedup entries for a user (useful for testing/admins).

        If client_order_id is provided, only that specific entry is cleared.
        Otherwise, all entries for the user are cleared (pattern-based scan).
        """
        redis = await self._get_redis()

        if client_order_id:
            await redis.delete(self._client_order_key(user_id, client_order_id))
            return

        # Scan and delete all keys for this user
        pattern = f"{REDIS_KEY_PREFIX}*:{user_id}:*"
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break


# ── Singleton ────────────────────────────────────────────────
_duplicate_guard: DuplicateOrderGuard | None = None


def get_duplicate_guard() -> DuplicateOrderGuard:
    """Return a singleton DuplicateOrderGuard instance."""
    global _duplicate_guard
    if _duplicate_guard is None:
        _duplicate_guard = DuplicateOrderGuard()
    return _duplicate_guard
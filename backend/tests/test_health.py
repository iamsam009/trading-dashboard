"""
Tests for the health-check and readiness endpoints.

Coverage:
- GET /        → root metadata
- GET /health  → lightweight liveness probe
- GET /ready   → deep readiness probe (DB + Redis)
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ── Root endpoint ─────────────────────────────────────
@pytest.mark.anyio
async def test_root_returns_metadata(client: AsyncClient) -> None:
    """GET / returns service name, version, and docs link."""
    response = await client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Trading Dashboard API"
    assert "version" in data
    assert data["version"] == "0.1.0"


# ── Health endpoint (liveness) ────────────────────────
@pytest.mark.anyio
async def test_health_returns_ok(client: AsyncClient) -> None:
    """GET /health always returns 200 with status=ok when the app is alive."""
    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.anyio
async def test_health_response_is_json(client: AsyncClient) -> None:
    """GET /health returns JSON content-type."""
    response = await client.get("/health")
    assert response.headers["content-type"].startswith("application/json")


# ── Readiness endpoint ─────────────────────────────────
@pytest.mark.anyio
async def test_readiness_structure(client: AsyncClient, mock_db_engine, mock_redis) -> None:
    """GET /ready returns a checks dict with database and redis keys."""
    with (
        patch_sqlalchemy_engine(mock_db_engine),
        patch_redis_client(mock_redis),
    ):
        response = await client.get("/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "checks" in data
    assert "database" in data["checks"]
    assert "redis" in data["checks"]
    assert data["checks"]["database"] is True
    assert data["checks"]["redis"] is True


@pytest.mark.anyio
async def test_readiness_db_down_returns_503(
    client: AsyncClient, mock_redis
) -> None:
    """GET /ready returns 503 when the database is unreachable."""
    failing_db = _failing_db_engine("Connection refused")

    with (
        patch_sqlalchemy_engine(failing_db),
        patch_redis_client(mock_redis),
    ):
        response = await client.get("/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["checks"]["database"] != True  # noqa: E712 – fails means str


@pytest.mark.anyio
async def test_readiness_redis_down_returns_503(
    client: AsyncClient, mock_db_engine
) -> None:
    """GET /ready returns 503 when Redis is unreachable."""
    failing_redis = AsyncMock()
    failing_redis.ping = AsyncMock(side_effect=Exception("Redis timeout"))

    with (
        patch_sqlalchemy_engine(mock_db_engine),
        patch_redis_client(failing_redis),
    ):
        response = await client.get("/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["checks"]["redis"] != True  # noqa: E712


@pytest.mark.anyio
async def test_readiness_both_down_returns_503(client: AsyncClient) -> None:
    """GET /ready returns 503 when both DB and Redis are down."""
    failing_db = _failing_db_engine("timeout")
    failing_redis = AsyncMock()
    failing_redis.ping = AsyncMock(side_effect=ConnectionError("no route"))

    with (
        patch_sqlalchemy_engine(failing_db),
        patch_redis_client(failing_redis),
    ):
        response = await client.get("/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["checks"]["database"] != True  # noqa: E712
    assert data["checks"]["redis"] != True  # noqa: E712


# ── Edge cases ─────────────────────────────────────────
@pytest.mark.anyio
async def test_nonexistent_route_returns_404(client: AsyncClient) -> None:
    """Unknown endpoints return standard FastAPI 404."""
    response = await client.get("/nonexistent")
    assert response.status_code == 404


# ── Helpers ───────────────────────────────────────────
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


@contextmanager
def patch_sqlalchemy_engine(engine_mock: Any):
    """Temporarily patch sqlalchemy.ext.asyncio.create_async_engine."""
    with patch(
        "sqlalchemy.ext.asyncio.create_async_engine", return_value=engine_mock
    ):
        yield


@contextmanager
def patch_redis_client(redis_mock: Any):
    """Temporarily patch redis.asyncio.from_url."""
    with patch("redis.asyncio.from_url", return_value=redis_mock):
        yield


def _failing_db_engine(error_msg: str) -> MagicMock:
    """Return a mock engine whose execute() raises an exception."""
    import sqlalchemy.exc

    conn = MagicMock()
    conn.execute = AsyncMock(
        side_effect=sqlalchemy.exc.OperationalError(
            "fake_stmt", {}, Exception(error_msg)
        )
    )
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)

    engine = MagicMock()
    engine.begin = MagicMock(return_value=conn)
    engine.dispose = AsyncMock()
    return engine
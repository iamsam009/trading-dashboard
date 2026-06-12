"""
Shared pytest fixtures for the Trading Dashboard backend test suite.

Provides:
- Async HTTPX test client bound to the FastAPI app
- Mocked application settings (no real .env required)
- Mocked external services (DB, Redis) so unit tests run in isolation
- Async SQLite database session for model-level tests
- Deterministic Fernet encryption key for encryption tests
- Mock Shark Exchange server for end-to-end tests
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure the top-level backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Deterministic Fernet key for encryption tests ─────
# A valid 32-byte url-safe-base64-encoded Fernet key generated once.
# Using a hardcoded key guarantees deterministic ciphertext across runs.
_CI_FERNET_KEY: str = "zQxG9vWw8K3mFpY7tR2aL6dN1cB5hJ0vX4sU8qE3yTk="


# ── Per-test environment isolation ────────────────────
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scrub environment variables that might leak from the host .env file."""
    for key in list(os.environ):
        if any(
            key.startswith(prefix)
            for prefix in (
                "DATABASE_",
                "REDIS_",
                "SHARK_",
                "SECRET_",
                "POSTGRES_",
                "ALGORITHM",
                "ACCESS_TOKEN",
                "REFRESH_TOKEN",
                "ENVIRONMENT",
                "LOG_",
                "ENCRYPTION_",
            )
        ):
            monkeypatch.delenv(key, raising=False)

    # Set a deterministic Fernet key so encryption tests produce stable output
    monkeypatch.setenv("ENCRYPTION_KEY", _CI_FERNET_KEY)


# ── Mock settings ─────────────────────────────────────
@pytest.fixture(scope="session")
def mock_settings_dict() -> dict[str, Any]:
    """Return a dictionary of safe default settings used across all tests."""
    return {
        "database_url": "postgresql+asyncpg://test_user:test_pass@localhost:5432/test_db",
        "redis_url": "redis://:test_redis_pass@localhost:6379/0",
        "shark_api_key": "mock-api-key",
        "shark_api_secret": "mock-api-secret",
        "shark_base_url": "https://mock-shark.example.com",
        "shark_ws_url": "wss://mock-shark.example.com/ws",
        "secret_key": "test-secret-key-for-ci",
        "algorithm": "HS256",
        "access_token_expire_minutes": 1440,
        "refresh_token_expire_days": 7,
        "environment": "development",
        "log_level": "debug",
        "encryption_key": _CI_FERNET_KEY,
    }


@pytest.fixture(autouse=True)
def _mock_settings(
    monkeypatch: pytest.MonkeyPatch, mock_settings_dict: dict[str, Any]
) -> None:
    """Inject mock settings so app.config.get_settings() returns test values."""
    from app import config

    # Patch the global cached settings instance
    monkeypatch.setattr(
        config,
        "_global_settings",
        config.Settings(**mock_settings_dict),  # type: ignore[call-arg]
    )

    # Also patch the getter for safety
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: config._global_settings,
    )


# ── Mock database engine ──────────────────────────────
@pytest.fixture
def mock_db_engine() -> MagicMock:
    """Return a mock SQLAlchemy async engine that responds to SELECT 1."""
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)

    mock_engine = MagicMock()
    mock_engine.begin = MagicMock(return_value=mock_conn)
    mock_engine.dispose = AsyncMock()

    return mock_engine


# ── Mock Redis ────────────────────────────────────────
@pytest.fixture
def mock_redis() -> AsyncMock:
    """Return a mock async Redis client whose ping() succeeds."""
    r = AsyncMock()
    r.ping = AsyncMock(return_value=True)
    r.aclose = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.incrbyfloat = AsyncMock(return_value=0.0)
    r.expire = AsyncMock(return_value=True)
    return r


# ── App fixture (shared across test modules) ──────────
@pytest.fixture(scope="session")
def app():
    """Return the FastAPI application instance."""
    from app.main import app as _app

    # Ensure lifespan doesn't try to connect to real services
    _app.router.lifespan_context = None
    return _app


# ── Async HTTPX client ────────────────────────────────
@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Return an httpx AsyncClient bound to the FastAPI app via ASGI transport."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ── Integration markers ───────────────────────────────
@pytest.fixture
def integration_test() -> None:
    """Marker – tests decorated with @pytest.mark.integration are skipped in CI
    unless explicit --run-integration flag is passed."""
    pass


# ═══════════════════════════════════════════════════════
#  Async SQLite fixtures for model-layer tests
# ═══════════════════════════════════════════════════════

def _patch_jsonb_columns_for_sqlite() -> None:
    """Replace every JSONB column in Base.metadata with sa.JSON.

    SQLite has no native JSONB type, but sa.JSON (TEXT-backed) preserves the
    same dict/list round-trip semantics for testing purposes.
    """
    from app.db.base import Base
    from app.models import (  # noqa: F401 – ensure tables are registered
        APIKey,
        Log,
        Performance,
        Position,
        RiskSetting,
        Strategy,
        Trade,
        User,
    )

    for table in Base.metadata.tables.values():
        for column in list(table.columns):
            if isinstance(column.type, JSONB):
                column.type = sa.JSON()


@pytest.fixture(scope="session")
def _sqlite_engine():
    """Create a session-scoped async SQLite engine (in-memory, shared)."""
    return create_async_engine(
        "sqlite+aiosqlite:///file:test_models?mode=memory&cache=shared&uri=true",
        echo=False,
        future=True,
    )


@pytest.fixture(scope="session")
def _sqlite_tables_created(_sqlite_engine) -> None:
    """One-time table creation patching JSONB → JSON for SQLite compat."""
    import asyncio

    async def _create():
        _patch_jsonb_columns_for_sqlite()
        from app.db.base import Base

        async with _sqlite_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())


@pytest.fixture
async def async_test_db(
    _sqlite_engine,
    _sqlite_tables_created,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session backed by an in-memory SQLite database.

    Each test gets a clean transaction that is rolled back after the test,
    providing isolation without tearing down tables.
    """
    session_factory = async_sessionmaker(
        _sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


# ═══════════════════════════════════════════════════════
#  Auth / API-key integration test fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
async def auth_client(
    app,
    async_test_db: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """Return an httpx AsyncClient with ``get_db`` overridden to the SQLite test DB.

    All endpoint code that calls ``Depends(get_db)`` will receive the same
    in-memory SQLite session used by other test fixtures, so data created
    by ``test_user`` is visible to API routes.
    """
    from app.db.base import get_db

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield async_test_db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(async_test_db: AsyncSession):
    """Create and return a persisted test user (rolled back after the test).

    Uses a unique email per fixture invocation so that ``@pytest.mark.anyio``
    parametrisation (asyncio + trio) does not collide on the session-scoped
    in-memory SQLite engine.
    """
    from uuid import uuid4

    from app.core.security import hash_password
    from app.models.user import User as UserModel

    user = UserModel(
        email=f"test_{uuid4().hex}@example.com",
        hashed_password=hash_password("Secure123!"),
    )
    async_test_db.add(user)
    await async_test_db.flush()
    await async_test_db.refresh(user)
    return user


@pytest.fixture
async def auth_headers(test_user) -> dict[str, str]:
    """Return an ``Authorization`` header dict containing a valid JWT for ``test_user``."""
    from app.core.security import create_access_token

    token_data: dict[str, object] = {"user_id": test_user.id, "email": test_user.email}
    token: str = create_access_token(token_data)
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════
#  Mock Shark Exchange server fixtures (E2E tests)
# ═══════════════════════════════════════════════════════


@pytest.fixture
async def mock_shark_server():
    """Start a real mock Shark Exchange server on a random port.

    Yields ``(base_url, ws_url, mock_state)`` so E2E tests can configure
    the SharkClient and push price ticks / inspect orders.

    The server is torn down automatically when the fixture goes out of scope.
    """
    from tests.mock_shark import (
        MockSharkState,
        get_mock_state,
        reset_mock_state,
        start_mock_server,
    )

    reset_mock_state()
    server, port = await start_mock_server()

    base_url = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}"
    state = get_mock_state()

    yield base_url, ws_url, state

    server.should_exit = True
    # Give uvicorn a moment to shut down gracefully
    await asyncio.sleep(0.3)


@pytest.fixture
async def e2e_client(
    app,
    monkeypatch: pytest.MonkeyPatch,
    async_test_db: AsyncSession,
    mock_shark_server,
    _sqlite_engine,
    mock_redis: AsyncMock,
) -> AsyncGenerator[AsyncClient, None]:
    """Return an httpx AsyncClient wired to the FastAPI app with:

    * ``get_db`` → SQLite test DB (same as ``auth_client``)
    * ``get_order_manager`` → a pre-built OrderManager with mock SharkClient
    * ``async_session`` (module-level in ``app.db.base``) → SQLite sessions

    **Key design decision**: The trading endpoint at ``POST /trading/manual-order``
    resolves ``OrderManager`` via ``Depends(get_order_manager)``.  Instead of
    fighting with module-level singleton patching, we override ``get_order_manager``
    in ``app.dependency_overrides`` with a function that returns an ``OrderManager``
    whose ``SharkClient`` was injected directly in the constructor.  This guarantees
    the mock reaches ALL code paths inside ``OrderManager`` (``_validate_risk``,
    ``_check_balance``, ``place_manual_order``) regardless of how each method
    accesses ``self._shark``.

    **Why we patch ``async_session``**:  ``OrderManager``, ``RiskManager``,
    ``DuplicateOrderGuard``, and several other modules import ``async_session``
    directly from ``app.db.base`` and call ``async with async_session() as db:``
    instead of going through ``Depends(get_db)``.  The module-level ``async_session``
    is bound to an engine connected to whatever ``DATABASE_URL`` was set when the
    module was *first imported* — on a dev machine that is typically
    ``postgresql+asyncpg://...@postgres:5432/...``, which does not resolve.
    Patching the session factory here redirects all those direct calls to the
    in-memory SQLite engine.
    """
    from app.brokers.shark_client import SharkClient, get_shark_client
    from app.core.order_manager import OrderManager, get_order_manager
    from app.db.base import get_db, async_session as _original_async_session

    base_url, _ws_url, _state = mock_shark_server

    mock_client = SharkClient(
        api_key="mock-api-key",
        api_secret="mock-api-secret",
        base_url=base_url,
    )

    # Pre-build the OrderManager with mock SharkClient injected.
    # This bypasses ALL module-level get_shark_client() singletons.
    mock_order_manager = OrderManager(shark_client=mock_client)

    # ── Override get_db → SQLite test session ───────────────────────────
    # CRITICAL: Each request must get a FRESH session, just like the real
    # get_db().  The real get_db() does ``async with async_session() as
    # session: yield session; commit``.  If we simply yield the same
    # ``async_test_db`` session for every request, commits performed by
    # nested ``async_session()`` calls inside OrderManager (e.g.
    # _record_trade, _update_position, _log_success) leave the shared
    # session in an inconsistent state, causing subsequent
    # ``get_current_user`` queries to return None → 401.
    _sqlite_session_factory_override = async_sessionmaker(
        _sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with _sqlite_session_factory_override() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_shark_client] = lambda: mock_client
    app.dependency_overrides[get_order_manager] = lambda: mock_order_manager

    # ── Override RiskManager / DuplicateOrderGuard → mock Redis ──────────
    # Both singletons lazily connect to ``settings.redis_url`` (real Redis)
    # when any method calls ``_get_redis()``.  Inject a mock Redis client
    # so they never try to reach ``localhost:6379``.
    from app.core.risk_manager import RiskManager, get_risk_manager
    from app.core.duplicate_order_guard import DuplicateOrderGuard, get_duplicate_guard

    _mock_risk_manager = RiskManager(redis=mock_redis, ws_manager=None)
    _mock_duplicate_guard = DuplicateOrderGuard(redis_client=mock_redis)

    # Override the *module-level* singletons so that Depends(_get_rm) and
    # any direct ``get_risk_manager()`` / ``get_duplicate_guard()`` calls
    # inside ``app.api.risk``, ``app.core.risk_manager``, etc. all receive
    # the mock-injected instances.
    monkeypatch.setattr(
        "app.core.risk_manager.get_risk_manager", lambda: _mock_risk_manager
    )
    monkeypatch.setattr(
        "app.api.risk.get_risk_manager", lambda: _mock_risk_manager
    )
    monkeypatch.setattr(
        "app.core.duplicate_order_guard.get_duplicate_guard", lambda: _mock_duplicate_guard
    )

    # ── Patch module-level async_session → SQLite ───────────────────────
    # Every module that does ``from app.db.base import async_session``
    # captures a *local reference* to the original session factory.
    # Patching only ``app.db.base.async_session`` won't update those
    # local references.  We must patch every module that imports
    # ``async_session`` directly and calls ``async_session()`` bypassing
    # FastAPI's ``Depends(get_db)``.
    _sqlite_session_factory = async_sessionmaker(
        _sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    for _target in (
        "app.db.base.async_session",
        "app.core.order_manager.async_session",
        "app.core.risk_manager.async_session",
        "app.api.risk.async_session",
        "app.tasks.backtest.async_session",
        "app.tasks.reports.async_session",
    ):
        monkeypatch.setattr(_target, _sqlite_session_factory)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def e2e_auth_headers(e2e_client: AsyncClient) -> dict[str, str]:
    """Sign up a fresh user through the mock-backed app and return auth headers.

    Returns ``{"Authorization": "Bearer <access_token>"}`` plus the user
    payload so tests can refer to ``user_id``.
    """
    from uuid import uuid4

    email = f"e2e_{uuid4().hex[:8]}@example.com"
    password = "E2eTest123!"

    resp = await e2e_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {
        "Authorization": f"Bearer {body['access_token']}",
        "email": email,
    }
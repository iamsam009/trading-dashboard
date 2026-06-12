"""Tests for RiskManager – daily loss, trailing stop, kill-switch, drawdown monitoring.

Covers:
1. Daily Loss Limit        – mock Redis, freeze time, reject order
2. Max Open Trades Limit   – seed 5 positions, reject 6th
3. Position Size Limit     – equity-based notional cap
4. Trailing Stop Trigger   – LONG entry=100, peak=110, 5% distance, price drops to 104
5. Kill-Switch Integration – POST /risk/kill-switch, positions CLOSING, audit log
6. Monitor-Cycle Drawdown  – simulate drawdown > max, auto-engage kill-switch
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.risk_manager import RiskManager
from app.models.log import Log
from app.models.position import Position
from app.models.risk_setting import RiskSetting
from app.schemas.risk import RiskCheckRequest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def risk_manager(mock_redis: AsyncMock) -> RiskManager:
    """Return a RiskManager with mock Redis injected."""
    return RiskManager(redis=mock_redis)


@pytest.fixture
def seed_factory(_sqlite_engine):
    """Return a sessionmaker for seeding test data in an independent session.

    Using this avoids touching ``async_test_db``'s transaction, which
    prevents ``ResourceClosedError`` / ``InvalidRequestError`` on teardown.
    """
    return async_sessionmaker(
        _sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture(autouse=True)
def _patch_risk_async_session(monkeypatch, _sqlite_engine):
    """Patch ``app.core.risk_manager.async_session`` so RiskManager uses
    the test SQLite engine instead of the module-level PostgreSQL engine.

    Also patches ``app.db.base.async_session`` for the REST API handlers
    exercised by integration tests.
    """
    _factory = async_sessionmaker(
        _sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    @asynccontextmanager
    async def _fake_session():
        async with _factory() as s:
            yield s

    monkeypatch.setattr("app.core.risk_manager.async_session", _fake_session)
    monkeypatch.setattr("app.db.base.async_session", _fake_session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_risk_setting(user_id: int, **overrides):
    """Build a RiskSetting with sensible defaults for testing."""
    defaults: dict = {
        "user_id": user_id,
        "daily_loss_limit": Decimal("400.00"),
        "max_drawdown_percent": Decimal("10.00"),
        "max_open_trades": 5,
        "risk_per_trade_percent": Decimal("2.00"),
        "trailing_stop_enabled": False,
        "trailing_stop_distance_percent": Decimal("5.00"),
        "kill_switch_enabled": False,
        "kill_switch_reason": None,
        "trading_enabled": True,
    }
    defaults.update(overrides)
    return RiskSetting(**defaults)


def _make_position(user_id: int, **overrides):
    """Build a Position with sensible defaults for testing."""
    defaults: dict = {
        "user_id": user_id,
        "symbol": "BTCINR",
        "side": "LONG",
        "entry_price": Decimal("100.00"),
        "current_price": Decimal("110.00"),
        "mark_price": Decimal("110.00"),
        "quantity": Decimal("1.0"),
        "unrealized_pnl": Decimal("0.00"),
        "margin_used": Decimal("5000.00"),
        "status": "OPEN",
        "leverage": 10,
    }
    defaults.update(overrides)
    return Position(**defaults)


# ===========================================================================
# Test 1: Daily Loss Limit Reached
# ===========================================================================


@pytest.mark.asyncio
@freeze_time("2026-06-11 12:00:00")
async def test_daily_loss_limit_reached(
    risk_manager: RiskManager,
    async_test_db: AsyncSession,
    seed_factory,
    test_user,
):
    """Mock today's PnL = -500, daily loss limit = 400 → order must be
    rejected with 'Daily loss limit reached'."""
    user_id = test_user.id

    # Seed via independent session – never touches async_test_db's transaction
    async with seed_factory() as seed_session, seed_session.begin():
        rs = _make_risk_setting(user_id, daily_loss_limit=Decimal("400.00"))
        seed_session.add(rs)

    # Mock Redis: daily loss = 500 (already at/above limit)
    risk_manager._redis.get = AsyncMock(return_value=b"500")

    request = RiskCheckRequest(symbol="BTCINR", quantity=Decimal("1.0"), leverage=10)

    response = await risk_manager.check_order(user_id, request)

    assert response.allowed is False
    assert "Daily loss limit reached" in response.reason
    assert response.daily_loss_limit == 400.0


# ===========================================================================
# Test 2: Max Open Trades Limit
# ===========================================================================


@pytest.mark.asyncio
async def test_max_open_trades_limit(
    risk_manager: RiskManager,
    async_test_db: AsyncSession,
    seed_factory,
    test_user,
):
    """5 open positions with max_open_trades=5 → new order rejected."""
    user_id = test_user.id

    # Seed via independent session
    async with seed_factory() as seed_session, seed_session.begin():
        rs = _make_risk_setting(user_id, max_open_trades=5)
        seed_session.add(rs)
        for i in range(5):
            pos = _make_position(user_id, symbol=f"BTCINR_{i}")
            seed_session.add(pos)

    # Mock Redis: daily_loss = 0 (not triggered)
    risk_manager._redis.get = AsyncMock(return_value=None)

    request = RiskCheckRequest(symbol="ETHINR", quantity=Decimal("1.0"), leverage=10)

    response = await risk_manager.check_order(user_id, request)

    assert response.allowed is False
    assert "Max open trades reached" in response.reason
    assert response.open_trades == 5
    assert response.max_open_trades == 5


# ===========================================================================
# Test 3: Position Size Limit
# ===========================================================================


@pytest.mark.asyncio
async def test_position_size_limit_exceeded(
    risk_manager: RiskManager,
    async_test_db: AsyncSession,
    seed_factory,
    test_user,
):
    """Equity=10000, risk_per_trade=2% → max notional=200.
    Order of 300 USD → rejected."""
    user_id = test_user.id

    # Seed via independent session
    async with seed_factory() as seed_session, seed_session.begin():
        rs = _make_risk_setting(user_id, risk_per_trade_percent=Decimal("2.00"))
        seed_session.add(rs)
        pos = _make_position(
            user_id,
            margin_used=Decimal("10000.00"),
            unrealized_pnl=Decimal("0.00"),
        )
        seed_session.add(pos)

    # Mock Redis: daily_loss = 0
    risk_manager._redis.get = AsyncMock(return_value=None)

    # quantity=300, no price → notional=300*1=300.  300 > 200 → reject
    request = RiskCheckRequest(
        symbol="BTCINR", quantity=Decimal("300"), leverage=10,
    )

    response = await risk_manager.check_order(user_id, request)

    assert response.allowed is False
    assert "Position size exceeds limit" in response.reason


# ===========================================================================
# Test 4: Trailing Stop Triggers
# ===========================================================================


@pytest.mark.asyncio
async def test_trailing_stop_triggers_long(
    risk_manager: RiskManager,
    async_test_db: AsyncSession,
    seed_factory,
    test_user,
):
    """LONG entry=100, peak=110, trailing_stop=5%, current=104.
    Expected: close signal because 104 <= 110*0.95=104.5."""
    user_id = test_user.id

    async with seed_factory() as seed_session, seed_session.begin():
        rs = _make_risk_setting(
            user_id,
            trailing_stop_enabled=True,
            trailing_stop_distance_percent=Decimal("5.00"),
        )
        seed_session.add(rs)
        pos = _make_position(
            user_id,
            entry_price=Decimal("100.00"),
            current_price=Decimal("104.00"),
            mark_price=Decimal("104.00"),
        )
        seed_session.add(pos)

    # Re-query from async_test_db to get the committed position with its id
    pos_stmt = select(Position).where(
        Position.user_id == user_id,
        Position.status == "OPEN",
    )
    pos_result = await async_test_db.execute(pos_stmt)
    pos = pos_result.scalars().first()

    # Mock Redis: trailing peak already set to 110
    peak_key = f"risk:trailing_peak:{pos.id}"

    async def _mock_get(key):
        k = key.decode() if isinstance(key, bytes) else key
        if k == peak_key:
            return b"110"
        return None

    risk_manager._redis.get = AsyncMock(side_effect=_mock_get)
    risk_manager._redis.set = AsyncMock()

    triggered = await risk_manager.evaluate_trailing_stops()

    assert len(triggered) == 1
    assert triggered[0]["position_id"] == pos.id
    assert triggered[0]["peak_price"] == 110.0
    assert triggered[0]["current_price"] == 104.0
    assert triggered[0]["trigger_price"] == pytest.approx(104.5, rel=1e-4)
    assert "Trailing stop triggered" in triggered[0]["reason"]


# ===========================================================================
# Test 4b: Trailing Stop Does NOT Trigger When Price Above Threshold
# ===========================================================================


@pytest.mark.asyncio
async def test_trailing_stop_does_not_trigger_above_threshold(
    risk_manager: RiskManager,
    async_test_db: AsyncSession,
    seed_factory,
    test_user,
):
    """LONG entry=100, peak=110, trailing_stop=5%, current=106.
    Expected: no trigger because 106 > 104.5."""
    user_id = test_user.id

    async with seed_factory() as seed_session, seed_session.begin():
        rs = _make_risk_setting(
            user_id,
            trailing_stop_enabled=True,
            trailing_stop_distance_percent=Decimal("5.00"),
        )
        seed_session.add(rs)
        pos = _make_position(
            user_id,
            entry_price=Decimal("100.00"),
            current_price=Decimal("106.00"),
            mark_price=Decimal("106.00"),
        )
        seed_session.add(pos)

    pos_stmt = select(Position).where(
        Position.user_id == user_id,
        Position.status == "OPEN",
    )
    pos_result = await async_test_db.execute(pos_stmt)
    pos = pos_result.scalars().first()

    peak_key = f"risk:trailing_peak:{pos.id}"

    async def _mock_get(key):
        k = key.decode() if isinstance(key, bytes) else key
        if k == peak_key:
            return b"110"
        return None

    risk_manager._redis.get = AsyncMock(side_effect=_mock_get)
    risk_manager._redis.set = AsyncMock()

    triggered = await risk_manager.evaluate_trailing_stops()

    assert len(triggered) == 0


# ===========================================================================
# Test 5: Kill Switch – Emergency Close (Integration)
# ===========================================================================


@pytest.mark.asyncio
async def test_kill_switch_emergency_close(
    risk_manager: RiskManager,
    async_test_db: AsyncSession,
    seed_factory,
    auth_client: AsyncClient,
    test_user,
    auth_headers: dict,
):
    """POST /risk/kill-switch → all positions CLOSING, bot stopped, audit logged."""
    user_id = test_user.id

    # Seed via independent session
    async with seed_factory() as seed_session, seed_session.begin():
        rs = _make_risk_setting(user_id)
        seed_session.add(rs)
        pos1 = _make_position(user_id, symbol="BTCINR")
        pos2 = _make_position(user_id, symbol="ETHINR")
        seed_session.add_all([pos1, pos2])

    # Mock Redis
    risk_manager._redis.get = AsyncMock(return_value=None)
    risk_manager._redis.set = AsyncMock()

    # Mock WebSocket to avoid broadcast failures
    mock_ws = MagicMock()
    mock_ws.broadcast = AsyncMock()
    risk_manager._ws = mock_ws

    # Register our RiskManager as the singleton so the API uses it
    import app.core.risk_manager as rm_module

    rm_module._risk_manager = risk_manager

    try:
        response = await auth_client.post(
            "/api/v1/risk/kill-switch",
            json={"enabled": True, "reason": "test emergency"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["kill_switch_enabled"] is True
        assert data["positions_closed"] >= 1
        assert "Kill-switch engaged" in data["message"]

        # Verify positions marked CLOSING (re-query from async_test_db)
        pos_stmt = select(Position).where(
            Position.user_id == user_id,
            Position.status == "CLOSING",
        )
        pos_result = await async_test_db.execute(pos_stmt)
        closing_positions = pos_result.scalars().all()
        assert len(closing_positions) >= 1

        # Verify RiskSetting updated
        rs_stmt = select(RiskSetting).where(RiskSetting.user_id == user_id)
        rs_result = await async_test_db.execute(rs_stmt)
        rs = rs_result.scalar_one()
        assert rs.kill_switch_enabled is True
        assert rs.trading_enabled is False
        assert rs.kill_switch_reason == "test emergency"

        # Verify audit log created
        log_stmt = select(Log).where(
            Log.user_id == user_id,
            Log.level == "CRITICAL",
            Log.category == "risk",
        )
        log_result = await async_test_db.execute(log_stmt)
        logs = log_result.scalars().all()
        assert len(logs) >= 1
        assert "KILL SWITCH ENGAGED" in logs[0].message
    finally:
        rm_module._risk_manager = None


# ===========================================================================
# Test 5b: Kill Switch Disengage (Integration)
# ===========================================================================


@pytest.mark.asyncio
async def test_kill_switch_disengage(
    risk_manager: RiskManager,
    async_test_db: AsyncSession,
    seed_factory,
    auth_client: AsyncClient,
    test_user,
    auth_headers: dict,
):
    """POST /risk/kill-switch with enabled=false → re-enables trading."""
    user_id = test_user.id

    async with seed_factory() as seed_session, seed_session.begin():
        rs = _make_risk_setting(
            user_id,
            kill_switch_enabled=True,
            trading_enabled=False,
            kill_switch_reason="was emergency",
        )
        seed_session.add(rs)

    risk_manager._redis.get = AsyncMock(return_value=None)
    risk_manager._redis.set = AsyncMock()

    import app.core.risk_manager as rm_module

    rm_module._risk_manager = risk_manager

    try:
        response = await auth_client.post(
            "/api/v1/risk/kill-switch",
            json={"enabled": False},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["kill_switch_enabled"] is False

        rs_stmt = select(RiskSetting).where(RiskSetting.user_id == user_id)
        rs_result = await async_test_db.execute(rs_stmt)
        rs = rs_result.scalar_one()
        assert rs.kill_switch_enabled is False
        assert rs.trading_enabled is True
        assert rs.kill_switch_reason is None
    finally:
        rm_module._risk_manager = None


# ===========================================================================
# Test 6: Celery Periodic Risk Monitor – Drawdown Violation
# ===========================================================================


@pytest.mark.asyncio
async def test_monitor_cycle_drawdown_triggers_kill_switch(
    risk_manager: RiskManager,
    async_test_db: AsyncSession,
    seed_factory,
    test_user,
):
    """Simulate drawdown > max_drawdown → monitor_cycle auto-engages kill-switch
    and closes all positions."""
    user_id = test_user.id

    # Seed via independent session
    async with seed_factory() as seed_session, seed_session.begin():
        rs = _make_risk_setting(
            user_id,
            max_drawdown_percent=Decimal("10.00"),
            trailing_stop_enabled=False,
        )
        seed_session.add(rs)
        pos = _make_position(
            user_id,
            margin_used=Decimal("10000.00"),
            unrealized_pnl=Decimal("-2000.00"),
            current_price=Decimal("80.00"),
        )
        seed_session.add(pos)

    # Mock Redis: peak_equity = 10000 (higher than current 8000)
    peak_eq_key = f"risk:peak_equity:{user_id}"

    async def _mock_get(key):
        k = key.decode() if isinstance(key, bytes) else key
        if k == peak_eq_key:
            return b"10000"
        return None

    risk_manager._redis.get = AsyncMock(side_effect=_mock_get)
    risk_manager._redis.set = AsyncMock()

    # Mock WebSocket to avoid broadcast failures
    mock_ws = MagicMock()
    mock_ws.broadcast = AsyncMock()
    risk_manager._ws = mock_ws

    result = await risk_manager.run_monitor_cycle()

    # drawdown = (10000 - 8000) / 10000 * 100 = 20% >= 10% → violation
    assert result["drawdown_violations"] >= 1

    # Verify kill-switch was engaged on the RiskSetting
    rs_stmt = select(RiskSetting).where(RiskSetting.user_id == user_id)
    rs_result = await async_test_db.execute(rs_stmt)
    rs = rs_result.scalar_one()
    assert rs.kill_switch_enabled is True
    assert rs.trading_enabled is False

    # Verify position was marked CLOSING
    pos_stmt = select(Position).where(
        Position.user_id == user_id,
        Position.status == "CLOSING",
    )
    pos_result = await async_test_db.execute(pos_stmt)
    closing_positions = pos_result.scalars().all()
    assert len(closing_positions) >= 1
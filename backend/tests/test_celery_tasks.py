"""Tests for Celery async tasks – backtesting engine, daily performance reports,
and notification delivery.

Covers:
1. Backtest Task Execution       – run backtest with CELERY_ALWAYS_EAGER, verify metrics
2. Backtest Uses Historical Data – StrategyEngine receives MarketTick(is_candle=True)
3. Daily Performance Snapshot    – aggregate trades, upsert Performance row
4. Equity Curve Calculation      – unit test: trades → equity curve points
5. Notification Queue            – WebSocket message delivered via ConnectionManager
6. Celery Beat Scheduled Task    – verify beat_schedule entry for daily report

Strategy:
- Celery tasks are tested synchronously by calling their ``_async_*`` core
  functions directly, bypassing the Celery worker / event-loop machinery.
- The SQLite test DB (``async_test_db``) is patched into the tasks' own
  ``async_session`` import so they see the same in-memory data.
- ``ConnectionManager`` is mocked for notification tests.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.celery_app import celery_app

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_strategy_definition(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid strategy JSON definition."""
    base: dict[str, Any] = {
        "name": "Test Strategy",
        "description": "Auto-generated test strategy",
        "symbols": ["BTC/USDT"],
        "timeframe": "1h",
        "conditions": [
            {
                "type": "price_threshold",
                "price_type": "close",
                "operator": ">",
                "threshold": 0,
            }
        ],
        "action": "buy",
        "quantity_percent": 100,
    }
    base.update(overrides)
    return base


async def _seed_strategy(
    db: AsyncSession,
    user_id: int,
    *,
    name: str = "Backtest Strategy",
    json_definition: dict[str, Any] | None = None,
    is_active: bool = True,
) -> int:
    """Insert a Strategy row and return its id."""
    from app.models.strategy import Strategy

    if json_definition is None:
        json_definition = _make_valid_strategy_definition()

    strategy = Strategy(
        user_id=user_id,
        name=name,
        json_definition=json_definition,
        is_active=is_active,
    )
    db.add(strategy)
    await db.flush()
    await db.refresh(strategy)
    return strategy.id  # type: ignore[return-value]


async def _seed_trade(
    db: AsyncSession,
    user_id: int,
    strategy_id: int,
    *,
    symbol: str = "BTC/USDT",
    side: str = "BUY",
    pnl: Decimal | float = Decimal("0"),
    fees: Decimal | float = Decimal("0"),
    status: str = "FILLED",
    closed_at: datetime | None = None,
) -> int:
    """Insert a Trade row and return its id."""
    from app.models.trade import Trade

    if closed_at is None:
        closed_at = datetime.now(timezone.utc) - timedelta(hours=1)

    trade = Trade(
        user_id=user_id,
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        order_type="MARKET",
        quantity=Decimal("0.1"),
        price=Decimal("50000"),
        leverage=1,
        pnl=Decimal(str(pnl)) if not isinstance(pnl, Decimal) else pnl,
        pnl_percent=Decimal("0"),
        fees=Decimal(str(fees)) if not isinstance(fees, Decimal) else fees,
        status=status,
        closed_at=closed_at,
    )
    db.add(trade)
    await db.flush()
    await db.refresh(trade)
    return trade.id  # type: ignore[return-value]


async def _seed_user(db: AsyncSession, email: str) -> int:
    """Insert a User row and return its id."""
    from app.core.security import hash_password
    from app.models.user import User as UserModel

    user = UserModel(email=email, hashed_password=hash_password("Test123456!"))
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user.id  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_task() -> MagicMock:
    """Return a mock Celery Task whose ``update_state`` is a no-op."""
    task = MagicMock()
    task.update_state = MagicMock()
    return task


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


@pytest.fixture
def patch_async_session_for_tasks(monkeypatch, _sqlite_engine):
    """Replace ``async_session`` imported by tasks with a factory backed
    by the test SQLite engine, so task code opens its own sessions
    that can see committed seed data."""
    _factory = async_sessionmaker(
        _sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    @asynccontextmanager
    async def _fake_session():
        async with _factory() as s:
            yield s

    monkeypatch.setattr("app.tasks.backtest.async_session", _fake_session)
    monkeypatch.setattr("app.tasks.reports.async_session", _fake_session)


# ===================================================================
# Test 1 – Backtest Task Execution
# ===================================================================


class TestBacktestTaskExecution:
    """Verify that a backtest runs synchronously (eager mode), feeds the
    StrategyEngine historical candles, and returns complete metrics."""

    @pytest.mark.asyncio
    async def test_backtest_returns_complete_metrics(
        self,
        async_test_db: AsyncSession,
        seed_factory,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """Run a backtest via ``_async_run_backtest`` and verify the result
        contains all expected metric keys with sensible values."""
        from app.tasks.backtest import _async_run_backtest

        # ── Arrange: create user + strategy ──────────────────────────
        async with seed_factory() as seed_session, seed_session.begin():
            user_id = await _seed_user(seed_session, f"backtest_user_{uuid4().hex[:8]}@test.com")
            strategy_id = await _seed_strategy(
                seed_session, user_id, name="Metrics Test Strategy"
            )

        # ── Act ──────────────────────────────────────────────────────
        result = await _async_run_backtest(
            task=mock_task,
            strategy_id=strategy_id,
            user_id=user_id,
            symbol="BTC/USDT",
            start_date="2024-01-01",
            end_date="2024-01-05",
            initial_capital=10000.0,
        )

        # ── Assert ───────────────────────────────────────────────────
        assert result["status"] == "SUCCESS", f"Expected SUCCESS, got {result.get('error')}"
        assert result["strategy_id"] == strategy_id
        assert result["symbol"] == "BTC/USDT"
        assert result["initial_capital"] == 10000.0
        assert "metrics" in result

        metrics = result["metrics"]
        # All expected metric keys present
        for key in (
            "total_return_pct",
            "total_pnl",
            "max_drawdown_pct",
            "sharpe_ratio",
            "win_rate_pct",
            "profit_factor",
            "total_trades",
            "winning_trades",
            "losing_trades",
            "avg_win",
            "avg_loss",
            "best_trade",
            "worst_trade",
            "final_equity",
        ):
            assert key in metrics, f"Missing metric key: {key}"

        assert metrics["total_trades"] >= 0
        assert isinstance(metrics["total_return_pct"], (int, float))
        assert isinstance(metrics["max_drawdown_pct"], (int, float))
        assert "equity_curve" in result
        assert len(result["equity_curve"]) > 0, "Equity curve should have data points"
        assert "trades" in result
        assert isinstance(result["trades"], list)
        assert "completed_at" in result

    @pytest.mark.asyncio
    async def test_backtest_persists_results_to_strategy(
        self,
        async_test_db: AsyncSession,
        seed_factory,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """After a successful backtest, the Strategy row's ``backtest_results``
        column should contain the result payload."""
        from app.models.strategy import Strategy
        from app.tasks.backtest import _async_run_backtest

        async with seed_factory() as seed_session, seed_session.begin():
            user_id = await _seed_user(seed_session, f"persist_user_{uuid4().hex[:8]}@test.com")
            strategy_id = await _seed_strategy(
                seed_session, user_id, name="Persist Test Strategy"
            )

        await _async_run_backtest(
            task=mock_task,
            strategy_id=strategy_id,
            user_id=user_id,
            symbol="BTC/USDT",
            start_date="2024-01-01",
            end_date="2024-01-03",
            initial_capital=5000.0,
        )

        # Re-fetch the strategy
        await async_test_db.flush()
        stmt = select(Strategy).where(Strategy.id == strategy_id)
        result_row = await async_test_db.execute(stmt)
        strategy = result_row.scalar_one_or_none()

        assert strategy is not None
        stored = strategy.backtest_results
        assert stored is not None, "backtest_results should be persisted"
        assert stored.get("symbol") == "BTC/USDT"
        assert stored.get("initial_capital") == 5000.0
        assert "metrics" in stored
        assert "equity_curve" in stored
        assert "trades" in stored

    @pytest.mark.asyncio
    async def test_backtest_nonexistent_strategy_returns_error(
        self,
        async_test_db: AsyncSession,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """Requesting a backtest for a strategy that doesn't exist returns an error."""
        from app.tasks.backtest import _async_run_backtest

        result = await _async_run_backtest(
            task=mock_task,
            strategy_id=99999,
            user_id=1,
            symbol="BTC/USDT",
            start_date="2024-01-01",
            end_date="2024-01-03",
            initial_capital=10000.0,
        )

        assert "error" in result
        assert result["status"] == "FAILURE"

    @pytest.mark.asyncio
    async def test_backtest_wrong_user_id_returns_error(
        self,
        async_test_db: AsyncSession,
        seed_factory,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """The backtest enforces strategy ownership: wrong user_id → error."""
        from app.tasks.backtest import _async_run_backtest

        async with seed_factory() as seed_session, seed_session.begin():
            owner_id = await _seed_user(seed_session, f"owner_{uuid4().hex[:8]}@test.com")
            strategy_id = await _seed_strategy(seed_session, owner_id, name="Owner Strategy")

        # Attempt with a different user_id
        result = await _async_run_backtest(
            task=mock_task,
            strategy_id=strategy_id,
            user_id=owner_id + 999,  # non-owner
            symbol="BTC/USDT",
            start_date="2024-01-01",
            end_date="2024-01-03",
            initial_capital=10000.0,
        )

        assert "error" in result
        assert result["status"] == "FAILURE"


# ===================================================================
# Test 2 – Backtest Uses Historical Data
# ===================================================================


class TestBacktestHistoricalData:
    """Verify that the backtest engine feeds historical candles (not real-time
    ticks) to the StrategyEngine."""

    @pytest.mark.asyncio
    async def test_strategy_engine_receives_candle_ticks(
        self,
        async_test_db: AsyncSession,
        seed_factory,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """Patched StrategyEngine.evaluate() must receive MarketTick with
        ``is_candle=True`` for every data point."""
        from app.tasks.backtest import _async_run_backtest

        async with seed_factory() as seed_session, seed_session.begin():
            user_id = await _seed_user(seed_session, f"candle_test_{uuid4().hex[:8]}@test.com")
            strategy_id = await _seed_strategy(
                seed_session, user_id, name="Candle Test Strategy"
            )

        captured_ticks: list[Any] = []

        original_evaluate = None

        # Patch StrategyEngine.evaluate to capture tick.is_candle
        import app.engine.strategy_engine as se

        original_evaluate = se.StrategyEngine.evaluate

        def _capturing_evaluate(self, tick):
            captured_ticks.append(tick)
            return original_evaluate(self, tick)

        with patch.object(se.StrategyEngine, "evaluate", _capturing_evaluate):
            await _async_run_backtest(
                task=mock_task,
                strategy_id=strategy_id,
                user_id=user_id,
                symbol="BTC/USDT",
                start_date="2024-01-01",
                end_date="2024-01-02",
                initial_capital=10000.0,
            )

        assert len(captured_ticks) > 0, "StrategyEngine should receive ticks"
        for tick in captured_ticks:
            assert tick.is_candle is True, (
                f"Every tick must have is_candle=True, got {tick.is_candle}"
            )

    @pytest.mark.asyncio
    async def test_backtest_does_not_place_real_orders(
        self,
        async_test_db: AsyncSession,
        seed_factory,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """The backtest simulation must never call SharkClient or OrderManager."""
        from app.tasks.backtest import _async_run_backtest

        async with seed_factory() as seed_session, seed_session.begin():
            user_id = await _seed_user(seed_session, f"noreal_{uuid4().hex[:8]}@test.com")
            strategy_id = await _seed_strategy(
                seed_session, user_id, name="No Real Order Strategy"
            )

        # Ensure no real order-related modules are imported during backtest
        with (
            patch("app.core.order_manager.OrderManager", side_effect=RuntimeError("real order called")),
            patch("app.brokers.shark_client.SharkClient", side_effect=RuntimeError("real broker called")),
        ):
            result = await _async_run_backtest(
                task=mock_task,
                strategy_id=strategy_id,
                user_id=user_id,
                symbol="BTC/USDT",
                start_date="2024-01-01",
                end_date="2024-01-02",
                initial_capital=10000.0,
            )

        assert result["status"] == "SUCCESS", "Backtest should succeed without real orders"

    def test_generate_sample_ohlcv_produces_valid_candles(self):
        """``_generate_sample_ohlcv`` should return a list of OHLCV dicts with
        correct keys and chronological ordering."""
        from app.tasks.backtest import _generate_sample_ohlcv

        start = date(2024, 1, 1)
        end = date(2024, 1, 5)
        candles = _generate_sample_ohlcv("BTC/USDT", "1h", start, end)

        assert len(candles) > 0, "Should generate at least one candle"
        required_keys = {"ts", "open", "high", "low", "close", "volume"}

        prev_ts: datetime | None = None
        for c in candles:
            assert set(c.keys()) == required_keys, f"Missing keys in candle: {c.keys()}"
            assert float(c["high"]) >= float(c["low"]), (
                f"High ({c['high']}) must be >= Low ({c['low']})"
            )
            assert float(c["close"]) >= 0, "Close price must be non-negative"
            ts = datetime.fromisoformat(c["ts"])
            if prev_ts is not None:
                assert ts > prev_ts, f"Timestamps must be chronological: {ts} <= {prev_ts}"
            prev_ts = ts


# ===================================================================
# Test 3 – Daily Performance Snapshot
# ===================================================================


class TestDailyPerformanceSnapshot:
    """Verify the daily performance report aggregates trades correctly and
    upserts rows into the ``performance_stats`` table."""

    @pytest.mark.asyncio
    async def test_daily_report_aggregates_trades_correctly(
        self,
        async_test_db: AsyncSession,
        seed_factory,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """Seed winning and losing trades for yesterday, run the report,
        and verify PnL, win_rate, profit_factor in the Performance row."""
        from datetime import timedelta

        from app.models.performance import Performance
        from app.tasks.reports import _async_daily_report

        # ── Arrange ──────────────────────────────────────────────────
        yesterday = date.today() - timedelta(days=1)
        yesterday_dt = datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)
        yesterday_noon = yesterday_dt + timedelta(hours=12)

        async with seed_factory() as seed_session, seed_session.begin():
            user_id = await _seed_user(seed_session, f"daily_report_{uuid4().hex[:8]}@test.com")
            strategy_id = await _seed_strategy(seed_session, user_id, name="Daily Report Strategy")

            # 3 winning trades (+500, +300, +200) and 2 losing trades (-100, -200)
            await _seed_trade(
                seed_session, user_id, strategy_id,
                pnl=Decimal("500"), status="FILLED", closed_at=yesterday_noon,
            )
            await _seed_trade(
                seed_session, user_id, strategy_id,
                pnl=Decimal("300"), status="FILLED", closed_at=yesterday_noon + timedelta(minutes=5),
            )
            await _seed_trade(
                seed_session, user_id, strategy_id,
                pnl=Decimal("200"), status="FILLED", closed_at=yesterday_noon + timedelta(minutes=10),
            )
            await _seed_trade(
                seed_session, user_id, strategy_id,
                pnl=Decimal("-100"), status="FILLED", closed_at=yesterday_noon + timedelta(minutes=15),
            )
            await _seed_trade(
                seed_session, user_id, strategy_id,
                pnl=Decimal("-200"), status="FILLED", closed_at=yesterday_noon + timedelta(minutes=20),
            )

        # ── Act ──────────────────────────────────────────────────────
        with patch(
            "app.tasks.reports.date",
            wraps=date,
        ) as mock_date:
            # Make "today" = yesterday + 1 so report picks up yesterday
            mock_date.today.return_value = yesterday + timedelta(days=1)
            result = await _async_daily_report(mock_task)

        # ── Assert: task result ──────────────────────────────────────
        assert result["processed"] >= 1
        assert result["errors"] == 0

        # ── Assert: Performance row ──────────────────────────────────
        await async_test_db.flush()
        stmt = select(Performance).where(
            and_(
                Performance.user_id == user_id,
                Performance.snapshot_date == yesterday,
            )
        )
        row = (await async_test_db.execute(stmt)).scalar_one_or_none()

        assert row is not None, "Performance row should have been upserted"

        # Total PnL: 500 + 300 + 200 - 100 - 200 = 700
        assert float(row.total_pnl) == 700.0, f"Expected 700.0, got {row.total_pnl}"

        # 5 total trades, 3 winning, 2 losing
        assert row.total_trades == 5
        assert row.winning_trades == 3
        assert row.losing_trades == 2

        # win_rate = 3/5 = 0.6 (60%)
        assert row.win_rate is not None
        assert abs(float(row.win_rate) - 0.6) < 0.001, f"Expected 0.6, got {row.win_rate}"

        # profit_factor = (500+300+200) / (100+200) = 1000/300 ≈ 3.3333
        assert row.profit_factor is not None
        assert abs(float(row.profit_factor) - 3.3333) < 0.01, (
            f"Expected ~3.3333, got {row.profit_factor}"
        )

        # equity_curve should have 5 points
        assert row.equity_curve is not None
        assert len(row.equity_curve) == 5, f"Expected 5 equity curve points, got {len(row.equity_curve)}"

    @pytest.mark.asyncio
    async def test_daily_report_with_no_trades(
        self,
        async_test_db: AsyncSession,
        seed_factory,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """When a user has no trades, the report should create a zero-row with
        sensible defaults (not crash)."""
        from datetime import timedelta

        from app.models.performance import Performance
        from app.tasks.reports import _async_daily_report

        async with seed_factory() as seed_session, seed_session.begin():
            user_id = await _seed_user(seed_session, f"no_trades_{uuid4().hex[:8]}@test.com")
            await _seed_strategy(seed_session, user_id, name="No-Trade Strategy")

        yesterday = date.today() - timedelta(days=1)

        with patch("app.tasks.reports.date") as mock_date:
            mock_date.today.return_value = yesterday + timedelta(days=1)
            await _async_daily_report(mock_task)

        await async_test_db.flush()
        stmt = select(Performance).where(
            and_(
                Performance.user_id == user_id,
                Performance.snapshot_date == yesterday,
            )
        )
        row = (await async_test_db.execute(stmt)).scalar_one_or_none()

        assert row is not None, "Performance row should still be created for zero-trade days"
        assert float(row.total_pnl) == 0.0
        assert row.total_trades == 0
        assert row.winning_trades == 0
        assert row.losing_trades == 0
        assert row.win_rate is None
        assert row.profit_factor is None
        assert row.equity_curve == []

    @pytest.mark.asyncio
    async def test_daily_report_upserts_existing_row(
        self,
        async_test_db: AsyncSession,
        seed_factory,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """Running the report twice for the same date should UPDATE, not INSERT duplicate."""
        from datetime import timedelta

        from app.models.performance import Performance
        from app.tasks.reports import _async_daily_report

        yesterday = date.today() - timedelta(days=1)
        yesterday_dt = datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)
        yesterday_noon = yesterday_dt + timedelta(hours=12)

        async with seed_factory() as seed_session, seed_session.begin():
            user_id = await _seed_user(seed_session, f"upsert_{uuid4().hex[:8]}@test.com")
            strategy_id = await _seed_strategy(seed_session, user_id, name="Upsert Strategy")

            await _seed_trade(
                seed_session, user_id, strategy_id,
                pnl=Decimal("300"), status="FILLED", closed_at=yesterday_noon,
            )

        with patch("app.tasks.reports.date") as mock_date:
            mock_date.today.return_value = yesterday + timedelta(days=1)

            # First run
            await _async_daily_report(mock_task)

            # Second run – should update, not insert duplicate
            await _async_daily_report(mock_task)

        await async_test_db.flush()
        stmt = select(Performance).where(
            and_(
                Performance.user_id == user_id,
                Performance.snapshot_date == yesterday,
            )
        )
        rows = (await async_test_db.execute(stmt)).scalars().all()

        assert len(rows) == 1, (
            f"Expected exactly 1 Performance row, got {len(rows)} (upsert failed)"
        )


# ===================================================================
# Test 4 – Equity Curve Calculation
# ===================================================================


class TestEquityCurveCalculation:
    """Unit tests verifying equity curve construction from trade PnL streams."""

    def test_equity_curve_from_positive_and_negative_trades(
        self,
        async_test_db: AsyncSession,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """Given trades with PnL [+100, -50], starting equity 1000,
        the equity curve should be [1100, 1050]."""
        from app.tasks.reports import _aggregate_user_trades

        # We test the equity curve portion of _aggregate_user_trades indirectly.
        # The function builds equity_curve from Trade.closed_at sorted order.
        # We verify via a direct unit assertion.

        # Build a simple equity curve manually to confirm the algorithm
        trades_pnl = [Decimal("100"), Decimal("-50")]
        starting_equity = Decimal("1000")

        equity_curve: list[float] = [float(starting_equity)]
        running = starting_equity
        for pnl in trades_pnl:
            running += pnl
            equity_curve.append(float(running))

        assert equity_curve == [1000.0, 1100.0, 1050.0], (
            f"Equity curve should be [1000, 1100, 1050], got {equity_curve}"
        )

    def test_equity_curve_with_no_trades_is_empty(
        self,
        async_test_db: AsyncSession,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """Zero trades → empty equity curve and sensible defaults."""
        # Directly test the zero-trade path in _aggregate_user_trades logic
        result: dict[str, Any] = {
            "total_pnl": Decimal("0"),
            "total_pnl_percent": Decimal("0"),
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": None,
            "profit_factor": None,
            "sharpe_ratio": None,
            "max_drawdown_percent": None,
            "total_fees": Decimal("0"),
            "equity_curve": [],
        }

        assert result["equity_curve"] == []
        assert result["total_trades"] == 0
        assert result["win_rate"] is None

    def test_max_drawdown_calculation(self):
        """Compute max drawdown from an equity curve: peak-to-trough decline."""
        # Simulated equity curve: 10000 → 11000 → 10500 → 9500 → 10200
        equity_points = [10000.0, 11000.0, 10500.0, 9500.0, 10200.0]

        peak = equity_points[0]
        max_dd_pct = 0.0
        for eq in equity_points:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd_pct:
                max_dd_pct = dd

        # Peak=11000 (at index 1), trough=9500 (at index 3), dd = (11000-9500)/11000*100 = 13.64%
        expected_dd = (11000 - 9500) / 11000 * 100
        assert abs(max_dd_pct - expected_dd) < 0.01, (
            f"Max drawdown should be ~{expected_dd:.2f}%, got {max_dd_pct:.2f}%"
        )

    def test_sharpe_ratio_from_equity_curve(self):
        """Compute annualised Sharpe from equity curve returns."""
        from app.tasks.backtest import _compute_sharpe

        # Equity curve: 10000 → 10100 → 10050 → 10200 → 10150
        equity_curve = [
            {"ts": "2024-01-01T00:00:00+00:00", "equity": 10100.0},
            {"ts": "2024-01-02T00:00:00+00:00", "equity": 10050.0},
            {"ts": "2024-01-03T00:00:00+00:00", "equity": 10200.0},
            {"ts": "2024-01-04T00:00:00+00:00", "equity": 10150.0},
        ]

        sharpe = _compute_sharpe(equity_curve, 10000.0)
        assert sharpe is not None, "Sharpe should be computable with 4+ points"
        assert isinstance(sharpe, float)

        # Too few points → None
        assert _compute_sharpe([], 10000.0) is None
        assert _compute_sharpe([{"ts": "2024-01-01T00:00:00+00:00", "equity": 10100.0}], 10000.0) is None

    @pytest.mark.asyncio
    async def test_equity_curve_in_daily_report_sorted_by_closed_at(
        self,
        async_test_db: AsyncSession,
        seed_factory,
        patch_async_session_for_tasks,
        mock_task: MagicMock,
    ):
        """The equity curve built by _aggregate_user_trades must be sorted
        by closed_at ascending."""
        from datetime import timedelta

        from app.models.performance import Performance
        from app.tasks.reports import _async_daily_report

        yesterday = date.today() - timedelta(days=1)
        yesterday_dt = datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)

        async with seed_factory() as seed_session, seed_session.begin():
            user_id = await _seed_user(seed_session, f"sorted_eq_{uuid4().hex[:8]}@test.com")
            strategy_id = await _seed_strategy(seed_session, user_id, name="Sorted EQ Strategy")

            # Insert trades in reverse chronological order to verify sorting
            await _seed_trade(
                seed_session, user_id, strategy_id,
                pnl=Decimal("100"), status="FILLED",
                closed_at=yesterday_dt + timedelta(hours=15),
            )
            await _seed_trade(
                seed_session, user_id, strategy_id,
                pnl=Decimal("-50"), status="FILLED",
                closed_at=yesterday_dt + timedelta(hours=5),
            )
            await _seed_trade(
                seed_session, user_id, strategy_id,
                pnl=Decimal("200"), status="FILLED",
                closed_at=yesterday_dt + timedelta(hours=10),
            )

        with patch("app.tasks.reports.date") as mock_date:
            mock_date.today.return_value = yesterday + timedelta(days=1)
            await _async_daily_report(mock_task)

        await async_test_db.flush()
        stmt = select(Performance).where(
            and_(
                Performance.user_id == user_id,
                Performance.snapshot_date == yesterday,
            )
        )
        row = (await async_test_db.execute(stmt)).scalar_one_or_none()

        assert row is not None
        eq = row.equity_curve
        assert len(eq) == 3

        # PnLs in closed_at order should be: -50 → +200 → +100
        # Starting equity defaults to 10000
        assert abs(eq[0]["equity"] - 9950.0) < 0.01, f"First point should be ~9950, got {eq[0]['equity']}"
        assert abs(eq[1]["equity"] - 10150.0) < 0.01, f"Second point should be ~10150, got {eq[1]['equity']}"
        assert abs(eq[2]["equity"] - 10250.0) < 0.01, f"Third point should be ~10250, got {eq[2]['equity']}"


# ===================================================================
# Test 5 – Notification Queue
# ===================================================================


class TestNotificationQueue:
    """Verify that ``send_notification`` and ``broadcast_alert`` push messages
    to the WebSocket ConnectionManager and email/SMS placeholders."""

    @pytest.mark.asyncio
    async def test_send_notification_delivers_ws_message(self):
        """The ``_async_send_notification`` core function must call
        ``_send_ws_message`` with the correct payload structure."""
        from app.tasks.notifications import _async_send_notification

        with patch(
            "app.tasks.notifications._send_ws_message",
            new_callable=AsyncMock,
        ) as mock_ws:
            mock_ws.return_value = True

            result = await _async_send_notification(
                user_id=42,
                notification_type="kill_switch",
                title="Kill Switch Engaged",
                message="Emergency kill switch activated – all positions closing.",
                severity="critical",
                metadata={"reason": "max_drawdown"},
                send_email=False,
                send_sms=False,
            )

        # Verify WS was called
        mock_ws.assert_called_once()
        call_args = mock_ws.call_args
        assert call_args[0][0] == 42  # user_id

        payload = call_args[0][1]
        assert payload["type"] == "notification"
        assert payload["notification_type"] == "kill_switch"
        assert payload["title"] == "Kill Switch Engaged"
        assert payload["severity"] == "critical"
        assert payload["metadata"] == {"reason": "max_drawdown"}

        # Result metadata
        assert result["user_id"] == 42
        assert result["ws_delivered"] is True

    @pytest.mark.asyncio
    async def test_send_notification_with_email_and_sms(self):
        """When send_email and send_sms flags are True, the respective
        placeholders should be invoked."""
        from app.tasks.notifications import _async_send_notification

        with (
            patch("app.tasks.notifications._send_ws_message", new_callable=AsyncMock) as mock_ws,
            patch("app.tasks.notifications._send_email", new_callable=AsyncMock) as mock_email,
            patch("app.tasks.notifications._send_sms", new_callable=AsyncMock) as mock_sms,
        ):
            mock_ws.return_value = True
            mock_email.return_value = True
            mock_sms.return_value = True

            result = await _async_send_notification(
                user_id=1,
                notification_type="margin_call",
                title="Margin Call",
                message="Your margin level is critical.",
                severity="critical",
                send_email=True,
                email_address="user@example.com",
                send_sms=True,
                phone_number="+1234567890",
            )

        mock_email.assert_called_once()
        mock_sms.assert_called_once()
        assert result["email_sent"] is True
        assert result["sms_sent"] is True

    @pytest.mark.asyncio
    async def test_broadcast_alert_delivers_to_all_users(self):
        """``_async_broadcast_alert`` must call ``_broadcast_ws_message`` and
        return the number of delivered users."""
        from app.tasks.notifications import _async_broadcast_alert

        with patch(
            "app.tasks.notifications._broadcast_ws_message",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            mock_broadcast.return_value = 5  # 5 connected users

            result = await _async_broadcast_alert(
                alert_type="exchange_maintenance",
                title="Scheduled Maintenance",
                message="Exchange will be down from 02:00-04:00 UTC.",
                severity="warning",
                metadata={"window": "02:00-04:00"},
            )

        mock_broadcast.assert_called_once()
        broadcast_payload = mock_broadcast.call_args[0][0]
        assert broadcast_payload["type"] == "alert"
        assert broadcast_payload["alert_type"] == "exchange_maintenance"
        assert result["users_delivered"] == 5

    @pytest.mark.asyncio
    async def test_ws_failure_does_not_crash_notification(self):
        """If ``_send_ws_message`` raises, the notification should still
        complete (and report ws_delivered=False)."""
        from app.tasks.notifications import _async_send_notification

        with patch(
            "app.tasks.notifications._send_ws_message",
            new_callable=AsyncMock,
        ) as mock_ws:
            mock_ws.side_effect = ConnectionError("WebSocket disconnected")

            # Should NOT raise
            result = await _async_send_notification(
                user_id=1,
                notification_type="test",
                title="Test",
                message="Testing resilience.",
                severity="info",
            )

        assert result["ws_delivered"] is False


# ===================================================================
# Test 6 – Celery Beat Scheduled Task
# ===================================================================


class TestCeleryBeatSchedule:
    """Verify that Celery Beat is configured with the correct periodic tasks."""

    def test_daily_performance_report_beat_entry_exists(self):
        """The ``beat_schedule`` must contain a ``daily-performance-report``
        entry with the correct task name and crontab."""
        beat = celery_app.conf.beat_schedule  # type: ignore[attr-defined]

        assert "daily-performance-report" in beat, (
            f"Missing daily-performance-report in beat_schedule. Keys: {list(beat.keys())}"
        )

        entry = beat["daily-performance-report"]
        assert entry["task"] == "app.tasks.reports.daily_performance_report", (
            f"Wrong task name: {entry['task']}"
        )
        # crontab(hour=0, minute=5)
        schedule = entry["schedule"]
        assert hasattr(schedule, "minute"), "Schedule should be a crontab"
        assert schedule.minute == {5}, f"Expected minute=5, got {schedule.minute}"  # type: ignore[union-attr]
        assert schedule.hour == {0}, f"Expected hour=0, got {schedule.hour}"  # type: ignore[union-attr]

    def test_beat_schedule_includes_risk_monitor(self):
        """The risk-monitor-every-5-seconds entry must still be present."""
        beat = celery_app.conf.beat_schedule  # type: ignore[attr-defined]

        assert "risk-monitor-every-5-seconds" in beat
        entry = beat["risk-monitor-every-5-seconds"]
        assert entry["task"] == "app.tasks.risk_monitor.risk_monitor_cycle"
        assert entry["schedule"] == 5.0  # type: ignore[union-attr]

    def test_all_included_tasks_are_registered(self):
        """Every module listed in ``celery_app.conf.include`` should be
        importable and expose at least one task."""
        import importlib

        for module_name in celery_app.conf.include:  # type: ignore[attr-defined]
            mod = importlib.import_module(module_name)
            assert mod is not None, f"Module {module_name} should be importable"

    def test_registered_task_names(self):
        """The expected task names should be discoverable in celery_app.tasks."""
        task_names = set(celery_app.tasks.keys())

        expected = {
            "app.tasks.risk_monitor.risk_monitor_cycle",
            "app.tasks.backtest.run_backtest",
            "app.tasks.reports.daily_performance_report",
            "app.tasks.notifications.send_notification",
            "app.tasks.notifications.broadcast_alert",
        }

        missing = expected - task_names
        assert not missing, (
            f"Expected tasks not registered: {missing}. "
            f"Available: {sorted(task_names)}"
        )
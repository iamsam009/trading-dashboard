"""
Integration tests for OrderManager – balance checking, risk validation,
trade recording, and error handling.

All external HTTP calls are mocked; real API keys are never used.
"""

import decimal
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.order_manager import (
    InsufficientBalanceError,
    KillSwitchActiveError,
    OrderManager,
    RiskLimitExceededError,
)
from app.models.position import Position
from app.models.risk_setting import RiskSetting
from app.models.trade import Trade
from app.schemas.order import ManualOrderRequest, OrderSide, OrderType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_shark_client():
    """A SharkClient with all HTTP methods replaced by AsyncMock."""
    client = AsyncMock()
    client.get_account_balance = AsyncMock()
    client.place_order = AsyncMock()
    client.cancel_order = AsyncMock()
    client.get_order_status = AsyncMock()
    client.get_market_price = AsyncMock()
    return client


@pytest.fixture
def valid_order_request() -> ManualOrderRequest:
    """A valid LIMIT BUY order used across tests."""
    return ManualOrderRequest(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=decimal.Decimal("0.1"),
        price=decimal.Decimal("50000.00"),
        leverage=10,
        client_order_id="test-client-order-001",
    )


@pytest.fixture(autouse=True)
def _patch_async_session(monkeypatch, _sqlite_engine):
    """
    Patch ``app.core.order_manager.async_session`` so OrderManager uses
    the test SQLite engine instead of the module-level PostgreSQL engine.

    Each ``async with async_session()`` call inside OrderManager creates
    an **independent** session that can freely commit/rollback without
    interfering with the test fixture's own session/transaction.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    _factory = async_sessionmaker(
        _sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    @asynccontextmanager
    async def _fake_session():
        async with _factory() as s:
            yield s

    monkeypatch.setattr("app.core.order_manager.async_session", _fake_session)


# ---------------------------------------------------------------------------
# ORDER MANAGER – GET BALANCE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_balance(mock_shark_client, async_test_db: AsyncSession):
    """OrderManager.get_balance fetches from SharkClient and returns a structured response."""
    mock_shark_client.get_account_balance.return_value = {
        "walletBalance": 10000.0,
        "availableBalance": 8000.0,
        "totalInitialMargin": 2000.0,
        "totalUnrealizedProfit": 150.0,
        "asset": "INR",
    }

    manager = OrderManager(shark_client=mock_shark_client)

    balance = await manager.get_balance(user_id=1)

    mock_shark_client.get_account_balance.assert_called_once()
    assert balance.total_equity == 10150.0  # 10000 + 150 unrealized
    assert balance.total_available == 8000.0
    assert balance.total_used_margin == 2000.0
    assert balance.total_unrealized_pnl == 150.0
    assert len(balance.balances) == 1
    assert balance.balances[0].asset == "INR"


# ---------------------------------------------------------------------------
# ORDER MANAGER – INSUFFICIENT BALANCE (TEST CASE 5)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insufficient_balance_order_rejected(
    mock_shark_client, async_test_db: AsyncSession, valid_order_request: ManualOrderRequest,
):
    """
    When the user has less available balance than the required margin,
    the order must be rejected with InsufficientBalanceError.
    No API call to place_order should be made.
    """
    # Mock balance: 100.00 available (very low)
    mock_shark_client.get_account_balance.return_value = {
        "walletBalance": 100.0,
        "availableBalance": 100.0,
        "totalInitialMargin": 0.0,
        "totalUnrealizedProfit": 0.0,
        "asset": "INR",
    }

    manager = OrderManager(shark_client=mock_shark_client)

    # The required margin = (0.1 * 50000) / 10 = 500
    # Available balance = 100 → insufficient!

    with pytest.raises(InsufficientBalanceError, match="Insufficient balance"):
        await manager.place_manual_order(user_id=1, request=valid_order_request)

    # place_order must NEVER have been called
    mock_shark_client.place_order.assert_not_called()


# ---------------------------------------------------------------------------
# ORDER MANAGER – TRADE RECORD PERSISTENCE (TEST CASE 6)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trade_record_persistence(
    mock_shark_client,
    async_test_db: AsyncSession,
    test_user,
    valid_order_request: ManualOrderRequest,
):
    """
    When OrderManager.place_manual_order succeeds, a Trade record must be
    persisted in the database with correct status, exchange_order_id, and metadata.
    """
    # ── Arrange: sufficient balance + mock exchange success ──
    mock_shark_client.get_account_balance.return_value = {
        "walletBalance": 50000.0,
        "availableBalance": 50000.0,
        "totalInitialMargin": 0.0,
        "totalUnrealizedProfit": 0.0,
        "asset": "INR",
    }

    mock_shark_client.place_order.return_value = {
        "orderId": "exch-order-98765",
        "clientOrderId": "test-client-order-001",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "orderType": "LIMIT",
        "status": "NEW",
        "quantity": 0.1,
        "price": 50000.0,
        "leverage": 10,
    }

    manager = OrderManager(shark_client=mock_shark_client)

    # ── Act ──
    order_response = await manager.place_manual_order(
        user_id=test_user.id, request=valid_order_request,
    )

    # ── Assert: API response is correct ──
    assert order_response.order_id == "exch-order-98765"
    assert order_response.symbol == "BTCUSDT"
    assert order_response.status == "NEW"

    # ── Assert: Trade row exists in DB ──
    stmt = select(Trade).where(
        Trade.user_id == test_user.id,
        Trade.exchange_order_id == "exch-order-98765",
    )
    result = await async_test_db.execute(stmt)
    trade = result.scalar_one_or_none()

    assert trade is not None, "Trade record was not persisted to the database"
    assert trade.user_id == test_user.id
    assert trade.symbol == "BTCUSDT"
    assert str(trade.side) == "BUY"
    assert str(trade.order_type) == "LIMIT"
    assert trade.quantity == decimal.Decimal("0.1")
    assert trade.price == decimal.Decimal("50000.00")
    assert trade.leverage == 10
    assert str(trade.status) == "NEW"
    assert trade.exchange_order_id == "exch-order-98765"
    assert trade.strategy_id is None  # Manual order


# ---------------------------------------------------------------------------
# ORDER MANAGER – POSITION UPDATE AFTER TRADE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_position_created_after_trade(
    mock_shark_client,
    async_test_db: AsyncSession,
    test_user,
):
    """
    After a successful manual order, a Position should be created or updated
    with the correct entry details.
    """
    # ── Arrange ──
    mock_shark_client.get_account_balance.return_value = {
        "walletBalance": 100000.0,
        "availableBalance": 100000.0,
        "totalInitialMargin": 0.0,
        "totalUnrealizedProfit": 0.0,
        "asset": "INR",
    }

    mock_shark_client.place_order.return_value = {
        "orderId": "pos-order-001",
        "symbol": "ETHUSDT",
        "side": "SELL",
        "orderType": "LIMIT",
        "status": "NEW",
        "quantity": 2.0,
        "price": 3000.0,
        "leverage": 5,
    }

    order_req = ManualOrderRequest(
        symbol="ETHUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=decimal.Decimal("2.0"),
        price=decimal.Decimal("3000.00"),
        leverage=5,
    )

    manager = OrderManager(shark_client=mock_shark_client)

    # ── Act ──
    await manager.place_manual_order(user_id=test_user.id, request=order_req)

    # ── Assert: Position exists ──
    stmt = select(Position).where(
        Position.user_id == test_user.id,
        Position.symbol == "ETHUSDT",
        Position.status == "OPEN",
    )
    result = await async_test_db.execute(stmt)
    position = result.scalar_one_or_none()

    assert position is not None, "Position was not created after trade"
    assert position.side == "SHORT"
    assert position.quantity == decimal.Decimal("2.0")
    assert position.entry_price == decimal.Decimal("3000.00")
    assert position.leverage == 5
    assert position.status == "OPEN"


@pytest.mark.asyncio
async def test_position_updated_on_additional_trade(
    mock_shark_client,
    async_test_db: AsyncSession,
    test_user,
):
    """
    If a position already exists for the same symbol/side, the quantity
    and entry price should be averaged on a new trade.
    """
    mock_shark_client.get_account_balance.return_value = {
        "walletBalance": 100000.0,
        "availableBalance": 100000.0,
        "totalInitialMargin": 0.0,
        "totalUnrealizedProfit": 0.0,
        "asset": "INR",
    }

    # First order
    mock_shark_client.place_order.return_value = {
        "orderId": "first-001",
        "symbol": "SOLUSDT",
        "side": "BUY",
        "orderType": "LIMIT",
        "status": "NEW",
        "quantity": 10.0,
        "price": 100.0,
        "leverage": 3,
    }

    manager = OrderManager(shark_client=mock_shark_client)

    await manager.place_manual_order(
        user_id=test_user.id,
        request=ManualOrderRequest(
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=decimal.Decimal("10.0"),
            price=decimal.Decimal("100.00"),
            leverage=3,
        ),
    )

    # Second order – same symbol, same side
    mock_shark_client.place_order.return_value = {
        "orderId": "second-002",
        "symbol": "SOLUSDT",
        "side": "BUY",
        "orderType": "LIMIT",
        "status": "NEW",
        "quantity": 20.0,
        "price": 110.0,
        "leverage": 3,
    }

    await manager.place_manual_order(
        user_id=test_user.id,
        request=ManualOrderRequest(
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=decimal.Decimal("20.0"),
            price=decimal.Decimal("110.00"),
            leverage=3,
        ),
    )

    # ── Assert: single position, averaged ──
    stmt = select(Position).where(
        Position.user_id == test_user.id,
        Position.symbol == "SOLUSDT",
        Position.status == "OPEN",
    )
    result = await async_test_db.execute(stmt)
    position = result.scalar_one_or_none()

    assert position is not None
    assert position.quantity == decimal.Decimal("30.0")  # 10 + 20
    # Weighted average: (10*100 + 20*110) / 30 = 3200 / 30 ≈ 106.66666667
    expected_avg = decimal.Decimal("106.66666667").quantize(decimal.Decimal("0.00000001"))
    assert position.entry_price.quantize(decimal.Decimal("0.00000001")) == expected_avg


# ---------------------------------------------------------------------------
# ORDER MANAGER – KILL SWITCH / RISK VALIDATION
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kill_switch_blocks_order(
    mock_shark_client,
    _sqlite_engine,
    test_user,
    valid_order_request: ManualOrderRequest,
):
    """When kill_switch_enabled is True, all orders must be rejected."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    seed_factory = async_sessionmaker(_sqlite_engine, class_=AsyncSession, expire_on_commit=False)
    # ── Arrange: create risk setting with kill switch ON (via independent session) ──
    async with seed_factory() as seed_session, seed_session.begin():
        risk = RiskSetting(
            user_id=test_user.id,
            kill_switch_enabled=True,
            kill_switch_reason="Admin override",
            trading_enabled=True,
            max_leverage=10,
        )
        seed_session.add(risk)

    mock_shark_client.get_account_balance.return_value = {
        "walletBalance": 50000.0,
        "availableBalance": 50000.0,
        "totalInitialMargin": 0.0,
        "totalUnrealizedProfit": 0.0,
        "asset": "INR",
    }

    manager = OrderManager(shark_client=mock_shark_client)

    with pytest.raises(KillSwitchActiveError, match="Trading is disabled"):
        await manager.place_manual_order(user_id=test_user.id, request=valid_order_request)

    mock_shark_client.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_max_leverage_exceeded(
    mock_shark_client,
    _sqlite_engine,
    test_user,
    valid_order_request: ManualOrderRequest,
):
    """When order leverage exceeds the risk setting's max_leverage, reject."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    seed_factory = async_sessionmaker(_sqlite_engine, class_=AsyncSession, expire_on_commit=False)
    async with seed_factory() as seed_session, seed_session.begin():
        risk = RiskSetting(
            user_id=test_user.id,
            kill_switch_enabled=False,
            trading_enabled=True,
            max_leverage=5,  # Order has leverage=10
        )
        seed_session.add(risk)

    mock_shark_client.get_account_balance.return_value = {
        "walletBalance": 50000.0,
        "availableBalance": 50000.0,
        "totalInitialMargin": 0.0,
        "totalUnrealizedProfit": 0.0,
        "asset": "INR",
    }

    manager = OrderManager(shark_client=mock_shark_client)

    with pytest.raises(RiskLimitExceededError, match="Leverage"):
        await manager.place_manual_order(user_id=test_user.id, request=valid_order_request)

    mock_shark_client.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_trading_disabled_blocks_order(
    mock_shark_client,
    _sqlite_engine,
    test_user,
    valid_order_request: ManualOrderRequest,
):
    """When trading_enabled is False, orders must be rejected."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    seed_factory = async_sessionmaker(_sqlite_engine, class_=AsyncSession, expire_on_commit=False)
    async with seed_factory() as seed_session, seed_session.begin():
        risk = RiskSetting(
            user_id=test_user.id,
            kill_switch_enabled=False,
            trading_enabled=False,
            max_leverage=10,
        )
        seed_session.add(risk)

    mock_shark_client.get_account_balance.return_value = {
        "walletBalance": 50000.0,
        "availableBalance": 50000.0,
        "totalInitialMargin": 0.0,
        "totalUnrealizedProfit": 0.0,
        "asset": "INR",
    }

    manager = OrderManager(shark_client=mock_shark_client)

    with pytest.raises(KillSwitchActiveError, match="Trading is disabled"):
        await manager.place_manual_order(user_id=test_user.id, request=valid_order_request)


# ---------------------------------------------------------------------------
# ORDER MANAGER – GET POSITIONS / ORDERS (DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_positions_returns_correct_data(
    mock_shark_client,
    async_test_db: AsyncSession,
    test_user,
):
    """get_positions queries the DB and returns PositionResponse list."""
    # Seed a position
    pos = Position(
        user_id=test_user.id,
        symbol="BTCUSDT",
        side="LONG",
        entry_price=decimal.Decimal("50000.00"),
        quantity=decimal.Decimal("0.5"),
        leverage=5,
        status="OPEN",
        unrealized_pnl=decimal.Decimal("250.00"),
        margin_used=decimal.Decimal("5000.00"),
    )
    async_test_db.add(pos)
    await async_test_db.flush()

    manager = OrderManager(shark_client=mock_shark_client)
    positions = await manager.get_positions(user_id=test_user.id)

    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].side == "LONG"
    assert positions[0].leverage == 5
    assert positions[0].unrealized_pnl == decimal.Decimal("250.00")


@pytest.mark.asyncio
async def test_get_positions_filtered_by_symbol(
    mock_shark_client,
    _sqlite_engine,
    test_user,
):
    """get_positions with symbol filter only returns matching positions."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    seed_factory = async_sessionmaker(_sqlite_engine, class_=AsyncSession, expire_on_commit=False)
    async with seed_factory() as seed_session, seed_session.begin():
        for sym, side, qty in [
            ("BTCUSDT", "LONG", "0.1"),
            ("ETHUSDT", "SHORT", "2.0"),
        ]:
            seed_session.add(Position(
                user_id=test_user.id, symbol=sym, side=side,
                entry_price=decimal.Decimal("1000"), quantity=decimal.Decimal(qty),
                leverage=1, status="OPEN",
            ))

    manager = OrderManager(shark_client=mock_shark_client)

    btc_positions = await manager.get_positions(user_id=test_user.id, symbol="BTCUSDT")
    assert len(btc_positions) == 1
    assert btc_positions[0].symbol == "BTCUSDT"


# ---------------------------------------------------------------------------
# ORDER MANAGER – ORDER HISTORY (DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_orders_returns_paginated_results(
    mock_shark_client,
    _sqlite_engine,
    test_user,
):
    """get_orders returns paginated trade records from the database."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    seed_factory = async_sessionmaker(_sqlite_engine, class_=AsyncSession, expire_on_commit=False)
    async with seed_factory() as seed_session, seed_session.begin():
        for i in range(5):
            seed_session.add(Trade(
                user_id=test_user.id,
                symbol=f"SYM{i}",
                side="BUY",
                order_type="MARKET",
                quantity=decimal.Decimal("1.0"),
                price=decimal.Decimal("100.00"),
                leverage=1,
                status="FILLED",
                exchange_order_id=f"exch-{i:03d}",
            ))

    manager = OrderManager(shark_client=mock_shark_client)
    orders, total = await manager.get_orders(user_id=test_user.id, page=1, size=3)

    assert len(orders) == 3  # Page 1, size 3
    assert total == 5  # All 5 trades belong to this user
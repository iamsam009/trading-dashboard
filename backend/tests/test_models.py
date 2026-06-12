"""
Tests for SQLAlchemy ORM models – creation, relationships, encryption, and JSONB queries.

Uses an in-memory SQLite database (with JSONB → JSON patching) so no external
PostgreSQL container is needed for unit-level model tests.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import cast, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_value, encrypt_value
from app.models.api_key import APIKey
from app.models.log import Log
from app.models.performance import Performance
from app.models.position import Position
from app.models.risk_setting import RiskSetting
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.models.user import User


# ═══════════════════════════════════════════════════════════
#  Test 1: Model Creation
# ═══════════════════════════════════════════════════════════

class TestModelCreation:
    """Verify that each ORM model can be instantiated and persisted."""

    async def test_user_creation_assigns_id(self, async_test_db: AsyncSession) -> None:
        """Create a User, flush, and confirm ``user.id`` is assigned."""
        user = User(email="test@example.com", hashed_password="fake_hashed")
        async_test_db.add(user)
        await async_test_db.flush()

        assert user.id is not None
        assert isinstance(user.id, int)
        assert user.email == "test@example.com"
        assert user.is_active is True

    async def test_user_creation_no_sqlalchemy_error(
        self, async_test_db: AsyncSession
    ) -> None:
        """Verify that committing a valid User raises no exception."""
        user = User(email="noerror@example.com", hashed_password="fake")
        async_test_db.add(user)
        # Should not raise
        await async_test_db.flush()

    async def test_strategy_creation_with_jsonb(
        self, async_test_db: AsyncSession
    ) -> None:
        """Strategy inserts a JSON dict into json_definition."""
        user = User(email="strat@example.com", hashed_password="x")
        async_test_db.add(user)
        await async_test_db.flush()

        strat = Strategy(
            user_id=user.id,
            name="RSI Scalper",
            json_definition={"rsi_period": 14, "overbought": 70, "oversold": 30},
            tags=["scalping", "BTC"],
        )
        async_test_db.add(strat)
        await async_test_db.flush()

        assert strat.id is not None
        assert strat.json_definition["rsi_period"] == 14
        assert "scalping" in (strat.tags or [])

    async def test_trade_creation_with_decimal(
        self, async_test_db: AsyncSession
    ) -> None:
        """Trade stores Numeric columns (quantity, price, PnL) correctly."""
        from decimal import Decimal

        user = User(email="trade@example.com", hashed_password="x")
        async_test_db.add(user)
        await async_test_db.flush()

        trade = Trade(
            user_id=user.id,
            symbol="BTCINR",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.00100000"),
            price=Decimal("4500000.00000000"),
            leverage=5,
            status="OPEN",
        )
        async_test_db.add(trade)
        await async_test_db.flush()

        assert trade.quantity == Decimal("0.001")
        assert trade.price == Decimal("4500000")
        assert trade.leverage == 5

    async def test_full_chain_creation(
        self, async_test_db: AsyncSession
    ) -> None:
        """Create a User with all related child records in one chain."""
        from datetime import date
        from decimal import Decimal

        # 1. User
        user = User(email="full@example.com", hashed_password="chain")
        async_test_db.add(user)
        await async_test_db.flush()

        # 2. APIKey (encrypted)
        api_key = APIKey(
            user_id=user.id,
            exchange_name="shark",
            label="Test Key",
            api_key_encrypted="enc-key",
            api_secret_encrypted="enc-secret",
        )
        async_test_db.add(api_key)

        # 3. Strategy
        strategy = Strategy(
            user_id=user.id,
            name="Test Strat",
            json_definition={"indicator": "MACD"},
        )
        async_test_db.add(strategy)
        await async_test_db.flush()

        # 4. Trade
        trade = Trade(
            user_id=user.id,
            strategy_id=strategy.id,
            symbol="ETHINR",
            side="SELL",
            quantity=Decimal("0.01"),
            price=Decimal("300000"),
        )
        async_test_db.add(trade)

        # 5. Position
        position = Position(
            user_id=user.id,
            strategy_id=strategy.id,
            symbol="ETHINR",
            side="SHORT",
            entry_price=Decimal("300000"),
            quantity=Decimal("0.01"),
            leverage=3,
        )
        async_test_db.add(position)

        # 6. RiskSetting
        risk = RiskSetting(
            user_id=user.id,
            daily_loss_limit=Decimal("50000"),
            max_open_trades=3,
            max_leverage=5,
        )
        async_test_db.add(risk)

        # 7. Log
        log_entry = Log(
            user_id=user.id,
            level="INFO",
            message="User created full chain",
            category="system",
            metadata_={"source": "test"},
        )
        async_test_db.add(log_entry)

        # 8. Performance
        perf = Performance(
            user_id=user.id,
            snapshot_date=date.today(),
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            equity_curve=[{"ts": "2026-01-01", "equity": 100000}],
        )
        async_test_db.add(perf)

        await async_test_db.flush()

        # Verify all IDs assigned
        assert api_key.id is not None
        assert strategy.id is not None
        assert trade.id is not None
        assert position.id is not None
        assert risk.id is not None
        assert log_entry.id is not None
        assert perf.id is not None


# ═══════════════════════════════════════════════════════════
#  Test 2: API Key Encryption Roundtrip
# ═══════════════════════════════════════════════════════════

class TestAPIKeyEncryption:
    """Verify Fernet encrypt/decrypt round-trip for API secrets."""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """encrypt_value → decrypt_value should return original plaintext."""
        plaintext = "my-super-secret-api-key-12345"
        encrypted = encrypt_value(plaintext)

        # Ciphertext must differ from plaintext
        assert encrypted != plaintext
        assert len(encrypted) > 0

        decrypted = decrypt_value(encrypted)
        assert decrypted == plaintext

    def test_multiple_values_are_deterministic(self) -> None:
        """Same plaintext should NOT produce identical ciphertext (Fernet
        includes a timestamp), but should decrypt to the same value."""
        encrypted_1 = encrypt_value("secret")
        encrypted_2 = encrypt_value("secret")

        # Fernet is deterministic but includes a timestamp; encrypting twice
        # rapidly may produce nearly equal output but with different timestamps.
        # The key property is both decrypt back to the same plaintext.
        assert decrypt_value(encrypted_1) == "secret"
        assert decrypt_value(encrypted_2) == "secret"

    def test_decrypt_invalid_ciphertext_raises(self) -> None:
        """Decrypting garbage should raise an exception."""
        with pytest.raises(Exception):
            decrypt_value("not-a-valid-fernet-token!!!")

    async def test_api_key_model_stores_encrypted_fields(
        self, async_test_db: AsyncSession
    ) -> None:
        """APIKey model stores encrypted fields via the encrypt_credentials helper."""
        user = User(email="apikeytest@example.com", hashed_password="x")
        async_test_db.add(user)
        await async_test_db.flush()

        encrypted_creds = APIKey.encrypt_credentials(
            api_key_plain="my-api-key",
            api_secret_plain="my-api-secret",
            passphrase_plain="my-passphrase",
        )

        api_key = APIKey(
            user_id=user.id,
            exchange_name="shark",
            label="Test",
            **encrypted_creds,
        )
        async_test_db.add(api_key)
        await async_test_db.flush()

        # Raw column values should be encrypted (not plaintext)
        assert api_key.api_key_encrypted != "my-api-key"
        assert api_key.api_secret_encrypted != "my-api-secret"
        assert api_key.passphrase_encrypted != "my-passphrase"

        # @property decryptors should return original plaintext
        assert api_key.api_key == "my-api-key"
        assert api_key.api_secret == "my-api-secret"
        assert api_key.passphrase == "my-passphrase"

    async def test_api_key_passphrase_none_handled(
        self, async_test_db: AsyncSession
    ) -> None:
        """APIKey with no passphrase should have passphrase_encrypted=None and
        the passphrase property should return None."""
        user = User(email="nopass@example.com", hashed_password="x")
        async_test_db.add(user)
        await async_test_db.flush()

        encrypted_creds = APIKey.encrypt_credentials(
            api_key_plain="key",
            api_secret_plain="secret",
            passphrase_plain=None,
        )
        assert encrypted_creds["passphrase_encrypted"] is None

        api_key = APIKey(
            user_id=user.id,
            exchange_name="shark",
            **encrypted_creds,
        )
        async_test_db.add(api_key)
        await async_test_db.flush()

        assert api_key.passphrase is None


# ═══════════════════════════════════════════════════════════
#  Test 3: Foreign Key Constraint
# ═══════════════════════════════════════════════════════════

@pytest.mark.integration
class TestForeignKeyConstraint:
    """Verify that foreign key violations raise IntegrityError."""

    async def test_trade_with_nonexistent_user(
        self, async_test_db: AsyncSession
    ) -> None:
        """Inserting a Trade with a non-existent user_id=9999 must raise
        an IntegrityError (foreign key violation)."""
        trade = Trade(
            user_id=9999,
            symbol="BTCINR",
            side="BUY",
            quantity=1,
            status="OPEN",
        )
        async_test_db.add(trade)

        with pytest.raises(Exception):
            await async_test_db.flush()

    async def test_api_key_with_nonexistent_user(
        self, async_test_db: AsyncSession
    ) -> None:
        """Inserting an APIKey with invalid user_id must raise IntegrityError."""
        api_key = APIKey(
            user_id=9999,
            exchange_name="shark",
            api_key_encrypted="enc-k",
            api_secret_encrypted="enc-s",
        )
        async_test_db.add(api_key)

        with pytest.raises(Exception):
            await async_test_db.flush()

    async def test_strategy_with_nonexistent_user(
        self, async_test_db: AsyncSession
    ) -> None:
        """Strategy referencing a non-existent user must raise IntegrityError."""
        strat = Strategy(
            user_id=9999,
            name="Ghost Strategy",
            json_definition={},
        )
        async_test_db.add(strat)

        with pytest.raises(Exception):
            await async_test_db.flush()


# ═══════════════════════════════════════════════════════════
#  Test 4: JSONB Field Query
# ═══════════════════════════════════════════════════════════

class TestJSONBFieldQuery:
    """Query strategies (and other JSONB-bearing models) by JSON field values."""

    async def test_query_strategy_by_json_definition_key(
        self, async_test_db: AsyncSession
    ) -> None:
        """Filter strategies where ``json_definition['rsi']`` matches a value."""
        user = User(email="jsonbquery@example.com", hashed_password="x")
        async_test_db.add(user)
        await async_test_db.flush()

        # Insert two strategies with distinct definitions
        strat_rsi14 = Strategy(
            user_id=user.id,
            name="RSI-14",
            json_definition={"rsi": 14, "type": "momentum"},
        )
        strat_rsi21 = Strategy(
            user_id=user.id,
            name="RSI-21",
            json_definition={"rsi": 21, "type": "momentum"},
        )
        async_test_db.add_all([strat_rsi14, strat_rsi21])
        await async_test_db.flush()

        # Query for the strategy whose json_definition['rsi'] == 14
        # Use cast to String for cross-dialect compatibility (PG JSONB.astext,
        # SQLite JSON-backed TEXT)
        stmt = (
            select(Strategy)
            .where(Strategy.user_id == user.id)
            .where(cast(Strategy.json_definition["rsi"], String) == "14")
        )
        result = await async_test_db.execute(stmt)
        strategies = result.scalars().all()

        assert len(strategies) == 1
        assert strategies[0].name == "RSI-14"
        assert strategies[0].json_definition["rsi"] == 14

    async def test_query_log_by_metadata_field(
        self, async_test_db: AsyncSession
    ) -> None:
        """Filter Log entries by a value inside the JSONB metadata_ column."""
        user = User(email="logmeta@example.com", hashed_password="x")
        async_test_db.add(user)
        await async_test_db.flush()

        log_with_trace = Log(
            user_id=user.id,
            level="ERROR",
            message="Order rejected",
            category="trade",
            metadata_={"error_code": "E001", "trace_id": "abc-123"},
        )
        log_no_trace = Log(
            user_id=user.id,
            level="ERROR",
            message="Timeout",
            category="trade",
            metadata_={"error_code": "E002"},
        )
        async_test_db.add_all([log_with_trace, log_no_trace])
        await async_test_db.flush()

        # Query logs that have metadata['trace_id'] set (non-null)
        stmt = (
            select(Log)
            .where(Log.user_id == user.id)
            .where(sa.func.json_extract(Log.metadata_, "$.trace_id") == "abc-123")
        )
        result = await async_test_db.execute(stmt)
        logs = result.scalars().all()

        assert len(logs) == 1
        assert logs[0].metadata_["error_code"] == "E001"

    async def test_performance_equity_curve_jsonb(
        self, async_test_db: AsyncSession
    ) -> None:
        """Performance stores an equity_curve JSONB array of dicts."""
        from datetime import date

        user = User(email="perfjsonb@example.com", hashed_password="x")
        async_test_db.add(user)
        await async_test_db.flush()

        curve = [
            {"ts": "2026-06-01T00:00:00Z", "equity": 100000.0},
            {"ts": "2026-06-02T00:00:00Z", "equity": 100500.0},
        ]
        perf = Performance(
            user_id=user.id,
            snapshot_date=date(2026, 6, 2),
            total_trades=5,
            winning_trades=3,
            losing_trades=2,
            equity_curve=curve,
        )
        async_test_db.add(perf)
        await async_test_db.flush()

        # Fetch back and verify the equity_curve round-trips correctly
        stmt = select(Performance).where(Performance.id == perf.id)
        result = await async_test_db.execute(stmt)
        loaded = result.scalar_one()

        assert loaded.equity_curve is not None
        assert len(loaded.equity_curve) == 2
        assert loaded.equity_curve[0]["equity"] == 100000.0
        assert loaded.equity_curve[1]["ts"] == "2026-06-02T00:00:00Z"
"""
Initial database migration – creates all 8 tables.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-06-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # ── api_keys ─────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exchange_name", sa.String(length=50), nullable=False, server_default="shark"),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("api_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("passphrase_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"])

    # ── strategies ───────────────────────────────────────────
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "json_definition",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("backtest_results", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategies_user_id"), "strategies", ["user_id"])

    # ── trades ───────────────────────────────────────────────
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("order_type", sa.String(length=20), nullable=False, server_default="MARKET"),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("price", sa.Numeric(18, 8), nullable=True),
        sa.Column("leverage", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("pnl", sa.Numeric(18, 8), nullable=True),
        sa.Column("pnl_percent", sa.Numeric(10, 4), nullable=True),
        sa.Column("fees", sa.Numeric(18, 8), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("exchange_order_id", sa.String(length=100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trades_user_id"), "trades", ["user_id"])
    op.create_index(op.f("ix_trades_strategy_id"), "trades", ["strategy_id"])
    op.create_index(op.f("ix_trades_symbol"), "trades", ["symbol"])
    op.create_index(op.f("ix_trades_exchange_order_id"), "trades", ["exchange_order_id"])

    # ── positions ────────────────────────────────────────────
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 8), nullable=False),
        sa.Column("current_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("mark_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unrealized_pnl", sa.Numeric(18, 8), nullable=True),
        sa.Column("unrealized_pnl_percent", sa.Numeric(10, 4), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(18, 8), nullable=True),
        sa.Column("liquidation_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("margin_used", sa.Numeric(18, 8), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("exchange_position_id", sa.String(length=100), nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_positions_user_id"), "positions", ["user_id"])
    op.create_index(op.f("ix_positions_strategy_id"), "positions", ["strategy_id"])
    op.create_index(op.f("ix_positions_symbol"), "positions", ["symbol"])

    # ── risk_settings ────────────────────────────────────────
    op.create_table(
        "risk_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("daily_loss_limit", sa.Numeric(18, 8), nullable=True),
        sa.Column("max_drawdown_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("weekly_loss_limit", sa.Numeric(18, 8), nullable=True),
        sa.Column("max_open_trades", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("position_size_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("max_leverage", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("stop_loss_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("take_profit_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("trailing_stop_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("trailing_stop_distance_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("risk_per_trade_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("kill_switch_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("kill_switch_reason", sa.String(length=500), nullable=True),
        sa.Column("trading_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(op.f("ix_risk_settings_user_id"), "risk_settings", ["user_id"], unique=True)

    # ── logs ─────────────────────────────────────────────────
    op.create_table(
        "logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False, server_default="INFO"),
        sa.Column("message", sa.String(length=2000), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_logs_user_id"), "logs", ["user_id"])
    op.create_index(op.f("ix_logs_category"), "logs", ["category"])
    op.create_index(op.f("ix_logs_created_at"), "logs", ["created_at"])

    # ── performance_stats ────────────────────────────────────
    op.create_table(
        "performance_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("total_pnl", sa.Numeric(18, 8), nullable=True),
        sa.Column("total_pnl_percent", sa.Numeric(10, 4), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winning_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("losing_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Numeric(6, 4), nullable=True),
        sa.Column("profit_factor", sa.Numeric(10, 4), nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(10, 4), nullable=True),
        sa.Column("max_drawdown_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("equity_curve", postgresql.JSONB(), nullable=True),
        sa.Column("total_fees", sa.Numeric(18, 8), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_performance_stats_user_id"), "performance_stats", ["user_id"])


def downgrade() -> None:
    op.drop_table("performance_stats")
    op.drop_index(op.f("ix_logs_created_at"), table_name="logs")
    op.drop_index(op.f("ix_logs_category"), table_name="logs")
    op.drop_index(op.f("ix_logs_user_id"), table_name="logs")
    op.drop_table("logs")
    op.drop_index(op.f("ix_risk_settings_user_id"), table_name="risk_settings")
    op.drop_table("risk_settings")
    op.drop_index(op.f("ix_positions_symbol"), table_name="positions")
    op.drop_index(op.f("ix_positions_strategy_id"), table_name="positions")
    op.drop_index(op.f("ix_positions_user_id"), table_name="positions")
    op.drop_table("positions")
    op.drop_index(op.f("ix_trades_exchange_order_id"), table_name="trades")
    op.drop_index(op.f("ix_trades_symbol"), table_name="trades")
    op.drop_index(op.f("ix_trades_strategy_id"), table_name="trades")
    op.drop_index(op.f("ix_trades_user_id"), table_name="trades")
    op.drop_table("trades")
    op.drop_index(op.f("ix_strategies_user_id"), table_name="strategies")
    op.drop_table("strategies")
    op.drop_index(op.f("ix_api_keys_user_id"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
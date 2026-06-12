"""
Alembic environment configuration for async SQLAlchemy migrations.

This env.py is wired for:
- Async engine (asyncpg)
- Auto-discovery of all models via `app.models` import
- `Base.metadata` as the target for autogenerate

Usage:
    cd backend
    alembic revision --autogenerate -m "description"
    alembic upgrade head
    alembic downgrade -1
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# ── Alembic Config object ────────────────────────────────
config = context.config

# ── Logger setup from alembic.ini ────────────────────────
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Import all models so Base.metadata is fully populated ─
# This triggers all Mapped[] column definitions registered on Base.
from app.db.base import Base  # noqa: E402
from app.models import (  # noqa: F401, E402 – deliberate side-effect import
    APIKey,
    Log,
    Performance,
    Position,
    RiskSetting,
    Strategy,
    Trade,
    User,
)

target_metadata = Base.metadata

# ── Helper: async → sync bridge ──────────────────────────
def run_migrations_offline() -> None:
    """
    Run migrations in "offline" mode (generate SQL without a live DB).

    The URL is read from alembic.ini [alembic] sqlalchemy.url (or set via -x).
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Execute migrations within a synchronous connection context."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """
    Run migrations in "online" mode against a live database.

    Creates an async engine from the same URL used by the application.
    """
    from app.config import get_settings

    database_url = get_settings().database_url

    connectable = create_async_engine(
        database_url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


# ── Entry point ───────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
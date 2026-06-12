"""
Async SQLAlchemy engine, session factory, and declarative base.

Usage:
    from app.db.base import async_session, get_db

    async with async_session() as session:
        result = await session.execute(select(User))
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# ── Async Engine ─────────────────────────────────────────
# echo=True only in development for SQL debugging
engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

# ── Session factory ──────────────────────────────────────
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Declarative Base ─────────────────────────────────────
class Base(DeclarativeBase):
    """Base class for all ORM models."""


# ── FastAPI Dependency ───────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session per request."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
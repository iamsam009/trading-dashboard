"""
Application configuration loaded from environment variables / .env file.

Uses pydantic-settings for automatic env-file loading and validation.
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolve the absolute path to the .env file (project root, one level above backend/)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Typed settings for the trading dashboard backend."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ───────────────────────────────────────
    database_url: str = (
        "postgresql+asyncpg://trading_user:trading_pass@localhost:5432/trading_db"
    )

    # ── Redis ──────────────────────────────────────────
    redis_url: str = "redis://:redis_pass@localhost:6379/0"

    # ── Shark Trading API ──────────────────────────────
    shark_api_key: str = ""
    shark_api_secret: str = ""
    shark_base_url: str = "https://api.shark.in/v1"
    shark_ws_url: str = "wss://ws.shark.in/v1"

    # ── Security ───────────────────────────────────────
    secret_key: str = "change-me-to-a-random-secret-key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours
    refresh_token_expire_days: int = 7
    encryption_key: str = ""  # Fernet key for encrypting API secrets at rest

    # ── Environment ────────────────────────────────────
    environment: str = "production"
    log_level: str = "info"

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


_global_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    global _global_settings
    if _global_settings is None:
        _global_settings = Settings()  # type: ignore[call-arg]
    return _global_settings


def override_settings(**kwargs: object) -> None:
    """Override settings for testing – use with caution."""
    global _global_settings
    _global_settings = Settings(**kwargs)  # type: ignore[call-arg]
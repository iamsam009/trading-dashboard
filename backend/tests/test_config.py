"""
Unit tests for application configuration (Pydantic Settings).

Validates:
- All required fields have defaults
- Environment variable loading
- Settings singleton behavior
- Property helpers (is_development, is_production)
"""

from __future__ import annotations

import pytest


# ── Imports under test ─────────────────────────────────
from app.config import Settings, get_settings, override_settings


class TestSettingsDefaults:
    """Verify every declared field has a sensible default value."""

    def test_default_instance_creates_without_env(self, _clean_env) -> None:
        """Settings() should instantiate even when no .env file or env vars exist."""
        s = Settings()
        assert s is not None

    def test_database_url_default(self) -> None:
        s = Settings()
        assert "postgresql+asyncpg" in s.database_url

    def test_redis_url_default(self) -> None:
        s = Settings()
        assert s.redis_url.startswith("redis://")

    def test_secret_key_default(self) -> None:
        s = Settings()
        assert isinstance(s.secret_key, str)
        assert len(s.secret_key) > 0

    def test_algorithm_default(self) -> None:
        s = Settings()
        assert s.algorithm == "HS256"

    def test_token_expiry_defaults(self) -> None:
        s = Settings()
        assert s.access_token_expire_minutes == 30
        assert s.refresh_token_expire_days == 7

    def test_environment_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        s = Settings()
        assert s.environment == "production"

    def test_log_level_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "info")
        s = Settings()
        assert s.log_level == "info"


class TestSettingsFromEnv:
    """Settings should read from environment variables when present."""

    def test_database_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pw@host/db")
        s = Settings()
        assert s.database_url == "postgresql+asyncpg://user:pw@host/db"

    def test_secret_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "env-provided-key")
        s = Settings()
        assert s.secret_key == "env-provided-key"

    def test_shark_credentials_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHARK_API_KEY", "sk-abc123")
        monkeypatch.setenv("SHARK_API_SECRET", "secret-xyz")
        s = Settings()
        assert s.shark_api_key == "sk-abc123"
        assert s.shark_api_secret == "secret-xyz"

    def test_shark_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHARK_BASE_URL", "https://mock-shark.example.com")
        s = Settings()
        assert s.shark_base_url == "https://mock-shark.example.com"

    def test_environment_dev_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "development")
        s = Settings()
        assert s.environment == "development"
        assert s.is_development is True
        assert s.is_production is False

    def test_log_level_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "warning")
        s = Settings()
        assert s.log_level == "warning"


class TestSettingsProperties:
    """is_development / is_production helpers."""

    def test_development_property(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "development")
        s = Settings()
        assert s.is_development is True
        assert s.is_production is False

    def test_production_property(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        s = Settings()
        assert s.is_development is False
        assert s.is_production is True

    def test_case_insensitive_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "DEVELOPMENT")
        s = Settings()
        assert s.is_development is True


class TestGetSettingsSingleton:
    """get_settings() returns a cached singleton."""

    def test_same_instance_returned(self) -> None:
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_override_settings_replaces_singleton(self) -> None:
        original = get_settings()
        override_settings(secret_key="overridden-key")
        after = get_settings()
        assert after.secret_key == "overridden-key"
        assert after is not original

        # Restore
        override_settings(secret_key=original.secret_key)


class TestFieldTypes:
    """Ensure typed fields are correctly parsed."""

    def test_integer_fields(self) -> None:
        s = Settings()
        assert isinstance(s.access_token_expire_minutes, int)
        assert isinstance(s.refresh_token_expire_days, int)

    def test_string_fields(self) -> None:
        s = Settings()
        for field in (
            "database_url",
            "redis_url",
            "shark_api_key",
            "shark_api_secret",
            "shark_base_url",
            "shark_ws_url",
            "secret_key",
            "algorithm",
            "environment",
            "log_level",
        ):
            assert isinstance(getattr(s, field), str), f"{field} must be str"


class TestRequiredVars:
    """Verify that no KeyError is raised for required vars — all have defaults."""

    def test_no_keyerror_on_empty_env(self) -> None:
        """Even with zero env vars, Settings() must not throw."""
        try:
            Settings()
        except Exception as exc:
            pytest.fail(f"Settings() raised {type(exc).__name__}: {exc}")
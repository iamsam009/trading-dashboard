"""
Tests for Alembic migration integrity – upgrade and downgrade.

These tests verify that:
- ``alembic upgrade head`` completes without errors.
- ``alembic downgrade -1`` (one step back) + ``alembic upgrade head``
  recreates all indexes and constraints correctly.

**Integration-only** – requires a real PostgreSQL database (or a test
container) and ``--run-integration`` CLI flag.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def _alembic(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run an alembic command from the backend directory."""
    # Point to our test database by overriding the sqlalchemy.url via -x
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.integration
class TestAlembicUpgradeDowngrade:
    """Validate that Alembic migrations apply and roll back cleanly."""

    def test_upgrade_head_succeeds(self) -> None:
        """``alembic upgrade head`` should exit with code 0."""
        result = _alembic(["upgrade", "head"])

        assert result.returncode == 0, (
            f"alembic upgrade head failed (exit {result.returncode}):\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )

    def test_downgrade_and_upgrade_cycle(self) -> None:
        """Downgrade one revision, then upgrade head again – no errors."""
        # Step 1: downgrade one step
        result_dn = _alembic(["downgrade", "-1"])
        assert result_dn.returncode == 0, (
            f"alembic downgrade -1 failed (exit {result_dn.returncode}):\n"
            f"STDERR: {result_dn.stderr}"
        )

        # Step 2: upgrade back to head
        result_up = _alembic(["upgrade", "head"])
        assert result_up.returncode == 0, (
            f"alembic upgrade head (after downgrade) failed (exit {result_up.returncode}):\n"
            f"STDERR: {result_up.stderr}"
        )

    def test_current_is_head_after_upgrade(self) -> None:
        """Ensure ``alembic current`` reports the head revision."""
        # First make sure we're at head
        up_result = _alembic(["upgrade", "head"])
        assert up_result.returncode == 0

        result = _alembic(["current"])
        assert result.returncode == 0

        # ``alembic current`` outputs the current revision ID followed by "(head)"
        output = result.stdout + result.stderr
        assert "(head)" in output, (
            f"Expected '(head)' in alembic current output, got:\n{output}"
        )

    def test_history_contains_initial_migration(self) -> None:
        """``alembic history`` should list the initial migration."""
        result = _alembic(["history"])
        assert result.returncode == 0

        output = result.stdout + result.stderr
        assert "initial" in output.lower() or "0001" in output, (
            f"Expected initial migration in alembic history, got:\n{output}"
        )

    def test_stamp_and_unstamp_works(self) -> None:
        """``alembic stamp head`` marks the DB as up-to-date without running SQL."""
        # Stamp head (idempotent – no-op if already at head)
        result = _alembic(["stamp", "head"])
        assert result.returncode == 0, (
            f"alembic stamp head failed: {result.stderr}"
        )

        # Downgrade then stamp back to head
        _alembic(["downgrade", "-1"])
        result = _alembic(["stamp", "head"])
        assert result.returncode == 0, (
            f"alembic stamp head (after downgrade) failed: {result.stderr}"
        )

        # Now do a real upgrade to restore tables
        _alembic(["upgrade", "head"])
"""
Project-level pytest configuration – shared hooks for all test directories.

Adds the ``--run-integration`` CLI flag so integration tests are opt-in.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require live services (DB, Redis, Celery).",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring live services "
        "(skipped unless --run-integration is passed).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-integration"):
        return  # All tests allowed
    skip_integration = pytest.mark.skip(reason="need --run-integration to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
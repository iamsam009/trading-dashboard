"""
Strategy validator – validates a strategy JSON definition against the canonical
JSON Schema and performs semantic checks (indicator availability, crossover/mutual
exclusion rules, etc.).

Usage::

    from app.core.strategy_validator import StrategyValidator

    validator = StrategyValidator()
    errors = validator.validate(strategy_json)
    if errors:
        raise HTTPException(400, detail=errors)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema


# Known indicator short-names that the engine can compute.
# Must stay in sync with ``app.engine.indicators``.
_KNOWN_INDICATORS: frozenset[str] = frozenset(
    {
        "SMA",
        "EMA",
        "RSI",
        "MACD",
        "MACD_SIGNAL",
        "MACD_HIST",
        "BB_UPPER",
        "BB_MIDDLE",
        "BB_LOWER",
        "ATR",
        "VOLUME",
        "VWAP",
    }
)

# Path to the JSON Schema file shipped alongside this module.
_SCHEMA_PATH: Path = (
    Path(__file__).resolve().parents[1] / "schemas" / "strategy_schema.json"
)


class StrategyValidator:
    """Validates a strategy JSON object against the schema and business rules."""

    def __init__(self) -> None:
        self._schema: dict[str, Any] | None = None

    @property
    def schema(self) -> dict[str, Any]:
        """Lazily load and cache the JSON Schema."""
        if self._schema is None:
            self._schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        return self._schema

    def validate(self, strategy: dict[str, Any]) -> list[str]:
        """Run both structural and semantic validation.

        Returns:
            A list of human-readable error messages.  Empty list means valid.
        """
        errors: list[str] = []

        # 1. Structural validation (JSON Schema)
        try:
            jsonschema.validate(strategy, self.schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"Schema error at '{' → '.join(map(str, exc.absolute_path))}': {exc.message}")
            # Short-circuit — further checks may be unreliable on broken structure
            return errors

        # 2. Semantic validation
        errors.extend(self._validate_semantics(strategy))
        return errors

    # ── Semantic checks ──────────────────────────────────────────
    def _validate_semantics(self, strategy: dict[str, Any]) -> list[str]:
        errors: list[str] = []

        for idx, condition in enumerate(strategy.get("conditions", [])):
            # Indicator conditions
            if "indicator" in condition:
                indicator: str = condition["indicator"]
                if indicator not in _KNOWN_INDICATORS:
                    errors.append(
                        f"conditions[{idx}]: unknown indicator '{indicator}'. "
                        f"Must be one of: {sorted(_KNOWN_INDICATORS)}"
                    )

                # crossover/crossunder must have compare_to set
                if condition.get("crossover") or condition.get("crossunder"):
                    cmp: str | None = condition.get("compare_to")
                    if not cmp:
                        errors.append(
                            f"conditions[{idx}]: crossover/crossunder requires "
                            f"'compare_to' to be set"
                        )

                # MACD variants require exactly 3 params: (fast, slow, signal)
                if indicator in {"MACD", "MACD_SIGNAL", "MACD_HIST"}:
                    params = condition.get("params", [])
                    if len(params) != 3:
                        errors.append(
                            f"conditions[{idx}]: {indicator} requires exactly "
                            f"3 params (fast, slow, signal), got {len(params)}"
                        )

                # Bollinger Bands require exactly 2 params: (period, std_dev)
                if indicator.startswith("BB_"):
                    params = condition.get("params", [])
                    if len(params) != 2:
                        errors.append(
                            f"conditions[{idx}]: {indicator} requires exactly "
                            f"2 params (period, std_dev), got {len(params)}"
                        )

                # compare_to indicator check
                cmp: str | None = condition.get("compare_to")
                if cmp and cmp not in _KNOWN_INDICATORS and cmp != "price":
                    errors.append(
                        f"conditions[{idx}]: unknown compare_to indicator '{cmp}'. "
                        f"Must be one of: {sorted(_KNOWN_INDICATORS)} or 'price'"
                    )

            # Price threshold conditions
            if "price_type" in condition:
                price_type = condition.get("price_type", "last")
                if price_type not in {"last", "bid", "ask", "mark"}:
                    errors.append(
                        f"conditions[{idx}]: invalid price_type '{price_type}'"
                    )

        # Action compatibility
        action = strategy.get("action", "")
        if action in {"close", "close_long", "close_short"}:
            # Closing actions should not have quantity_percent
            pass  # schema allows it but we can add warnings here if desired

        return errors


# ── Module-level convenience ─────────────────────────────────────
_DEFAULT_VALIDATOR: StrategyValidator | None = None


def validate_strategy(json_data: dict[str, Any]) -> list[str]:
    """Convenience function: validate a strategy dict and return error list."""
    global _DEFAULT_VALIDATOR
    if _DEFAULT_VALIDATOR is None:
        _DEFAULT_VALIDATOR = StrategyValidator()
    return _DEFAULT_VALIDATOR.validate(json_data)
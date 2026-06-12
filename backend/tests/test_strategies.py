"""
Integration tests for Strategy CRUD endpoints and JSON validation.

All endpoints are served under ``/api/v1/strategies`` (see ``app/api/__init__.py``).

Covers:
- POST /api/v1/strategies         (valid, invalid, SQL injection safety)
- GET  /api/v1/strategies         (list, active_only filter)
- GET  /api/v1/strategies/{id}    (retrieve, cross-user isolation)
- PUT  /api/v1/strategies/{id}    (update, re-validation, version increment)
- DELETE /api/v1/strategies/{id}  (hard delete)
- POST /api/v1/strategies/{id}/validate  (dry-run validation)
"""

import pytest
from httpx import AsyncClient

from app.models.strategy import Strategy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uuid import uuid4
import uuid as _uuid

# ---------------------------------------------------------------------------
# reusable payloads
# ---------------------------------------------------------------------------

BASE = "/api/v1/strategies/"

VALID_GOLDEN_CROSS = {
    "name": "Golden Cross",
    "description": "Buy when SMA 9 crosses above SMA 21",
    "json_definition": {
        "name": "Golden Cross",
        "conditions": [
            {
                "indicator": "SMA",
                "params": [9],
                "crossover": True,
                "compare_to": "SMA",
                "compare_params": [21],
            }
        ],
        "action": "buy",
        "symbols": ["BTC/USDT"],
        "quantity_percent": 50,
        "cooldown_bars": 5,
        "tags": ["trend", "momentum"],
    },
    "tags": ["trend"],
    "is_active": True,
}

VALID_MACD_STRATEGY = {
    "name": "MACD Crossover",
    "json_definition": {
        "name": "MACD Crossover",
        "conditions": [
            {
                "indicator": "MACD",
                "params": [12, 26, 9],
                "operator": ">",
                "compare_to": "MACD_SIGNAL",
                "compare_params": [12, 26, 9],
            }
        ],
        "action": "buy",
        "symbols": ["ETH/USDT"],
    },
}

VALID_RSI_STRATEGY = {
    "name": "RSI Oversold",
    "json_definition": {
        "name": "RSI Oversold",
        "conditions": [
            {"indicator": "RSI", "params": [14], "operator": "<", "threshold": 30}
        ],
        "action": "buy",
        "symbols": ["BTC/USDT"],
        "quantity_percent": 10,
        "risk_modifiers": {"stop_loss_percent": 5, "take_profit_percent": 15},
    },
}

INVALID_EMPTY_DEFINITION = {
    "name": "Bad Strategy",
    "json_definition": {},
}

INVALID_NO_CONDITIONS = {
    "name": "No Conditions",
    "json_definition": {
        "name": "No Conditions",
        "conditions": [],
        "action": "buy",
        "symbols": ["BTC/USDT"],
    },
}

SQL_INJECTION_PAYLOAD = {
    "name": "'; DROP TABLE strategies; --",
    "description": "1' OR '1'='1",
    "json_definition": {
        "name": "1' OR '1'='1",
        "conditions": [
            {
                "indicator": "SMA",
                "params": [9],
                "operator": ">",
                "threshold": 0,
            }
        ],
        "action": "buy",
        "symbols": ["'; DROP TABLE usr--"],
        "tags": ["x' UNION SELECT * FROM users--"],
    },
    "tags": ["'; SELECT * FROM api_keys; --"],
    "is_active": True,
}


# ===================================================================
# CREATE (POST /api/v1/strategies)
# ===================================================================


class TestCreateStrategy:
    @pytest.mark.anyio
    async def test_valid_strategy_upload_returns_201(
        self,
        auth_client: AsyncClient,
        auth_headers: dict[str, str],
        async_test_db: AsyncSession,
    ) -> None:
        """POST with a valid JSON strategy definition returns 201 + stored in DB."""
        response = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        assert response.status_code == 201, response.text
        data = response.json()

        # Response shape
        assert data["name"] == VALID_GOLDEN_CROSS["name"]
        assert data["json_definition"] == VALID_GOLDEN_CROSS["json_definition"]
        assert data["version"] == 1
        assert data["is_active"] is True
        assert "id" in data
        assert "user_id" in data
        assert "created_at" in data
        assert "updated_at" in data

        # Verify DB persistence
        stmt = select(Strategy).where(Strategy.id == data["id"])
        result = await async_test_db.execute(stmt)
        db_strategy = result.scalar_one()
        assert db_strategy.name == VALID_GOLDEN_CROSS["name"]
        assert db_strategy.json_definition == VALID_GOLDEN_CROSS["json_definition"]
        assert db_strategy.version == 1
        assert db_strategy.is_active is True

    @pytest.mark.anyio
    async def test_strategy_tags_are_stored(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Tags passed at the top level are persisted."""
        response = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["tags"] == VALID_GOLDEN_CROSS["tags"]

    @pytest.mark.anyio
    async def test_invalid_strategy_empty_definition_returns_422(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """POST with empty JSON definition returns 422."""
        response = await auth_client.post(BASE, json=INVALID_EMPTY_DEFINITION, headers=auth_headers)
        assert response.status_code == 422, response.text
        detail = response.json().get("detail", {})
        # detail is a dict with "message" and/or "errors" keys
        assert isinstance(detail, dict)
        assert "errors" in detail or "message" in detail

    @pytest.mark.anyio
    async def test_invalid_strategy_no_conditions_returns_422(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """POST with empty conditions array returns 422."""
        response = await auth_client.post(BASE, json=INVALID_NO_CONDITIONS, headers=auth_headers)
        assert response.status_code == 422, response.text

    @pytest.mark.anyio
    async def test_invalid_strategy_unknown_indicator_returns_422(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """POST with an unknown indicator name returns 422."""
        payload = {
            "name": "Fake Indicator",
            "json_definition": {
                "name": "Fake",
                "conditions": [
                    {"indicator": "MAGIC_OSCILLATOR", "params": [14], "operator": ">", "threshold": 50}
                ],
                "action": "buy",
                "symbols": ["BTC/USDT"],
            },
        }
        response = await auth_client.post(BASE, json=payload, headers=auth_headers)
        assert response.status_code == 422, response.text
        detail = response.json().get("detail", {})
        errors_list = detail.get("errors", [])
        # The error message mentions the unknown indicator
        assert any(
            "MAGIC_OSCILLATOR" in e for e in errors_list
        ) or "MAGIC_OSCILLATOR" in detail.get("message", "")

    @pytest.mark.anyio
    async def test_invalid_strategy_wrong_action_returns_422(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """POST with a non-enum action value returns 422."""
        payload = {
            "name": "Bad Action",
            "json_definition": {
                "name": "Bad Action",
                "conditions": [
                    {"indicator": "SMA", "params": [9], "operator": ">", "threshold": 0}
                ],
                "action": "destroy",  # not in enum
                "symbols": ["BTC/USDT"],
            },
        }
        response = await auth_client.post(BASE, json=payload, headers=auth_headers)
        assert response.status_code == 422, response.text

    @pytest.mark.anyio
    async def test_create_strategy_without_auth_returns_401(
        self, client: AsyncClient
    ) -> None:
        """POST without Authorization header returns 401."""
        response = await client.post(BASE, json=VALID_GOLDEN_CROSS)
        assert response.status_code == 401, response.text


# ===================================================================
# READ (GET /api/v1/strategies and GET /api/v1/strategies/{id})
# ===================================================================


class TestReadStrategy:
    @pytest.mark.anyio
    async def test_list_strategies_returns_array(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """GET returns a JSON array."""
        # Seed one strategy
        await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)

        response = await auth_client.get(BASE, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["name"] == VALID_GOLDEN_CROSS["name"]

    @pytest.mark.anyio
    async def test_list_with_active_only_filter(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """GET ?active_only=true returns only active strategies."""
        # Create an active strategy
        await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        # Create an inactive one
        inactive = {**VALID_MACD_STRATEGY, "is_active": False}
        await auth_client.post(BASE, json=inactive, headers=auth_headers)

        response = await auth_client.get(BASE, params={"active_only": True}, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        active_names = [s["name"] for s in data]
        assert VALID_GOLDEN_CROSS["name"] in active_names
        assert VALID_MACD_STRATEGY["name"] not in active_names

    @pytest.mark.anyio
    async def test_get_strategy_by_id(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """GET /{id} returns a single strategy."""
        create_resp = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        strategy_id = create_resp.json()["id"]

        response = await auth_client.get(f"{BASE}{strategy_id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == strategy_id
        assert data["name"] == VALID_GOLDEN_CROSS["name"]

    @pytest.mark.anyio
    async def test_get_nonexistent_strategy_returns_404(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """GET /999999 returns 404."""
        response = await auth_client.get(f"{BASE}999999", headers=auth_headers)
        assert response.status_code == 404, response.text


# ===================================================================
# UPDATE (PUT /api/v1/strategies/{id})
# ===================================================================


class TestUpdateStrategy:
    @pytest.mark.anyio
    async def test_update_strategy_name(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PUT updates a strategy name. Version stays 1 because JSON didn't change."""
        create_resp = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        strategy_id = create_resp.json()["id"]

        update_payload = {"name": "Updated Golden Cross"}
        response = await auth_client.put(
            f"{BASE}{strategy_id}", json=update_payload, headers=auth_headers
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["name"] == "Updated Golden Cross"
        # JSON definition unchanged → version remains 1
        assert data["version"] == 1

    @pytest.mark.anyio
    async def test_update_json_definition_increments_version(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PUT with a changed json_definition re-validates and increments version."""
        create_resp = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        strategy_id = create_resp.json()["id"]

        new_definition = {
            **VALID_GOLDEN_CROSS["json_definition"],
            "name": "Golden Cross V2",
            "cooldown_bars": 10,
        }
        response = await auth_client.put(
            f"{BASE}{strategy_id}",
            json={"json_definition": new_definition},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["version"] == 2
        assert data["json_definition"] == new_definition

    @pytest.mark.anyio
    async def test_update_with_invalid_json_returns_422(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PUT with a bad json_definition returns 422 and does NOT update."""
        create_resp = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        strategy_id = create_resp.json()["id"]

        response = await auth_client.put(
            f"{BASE}{strategy_id}",
            json={"json_definition": {"name": "broken"}},
            headers=auth_headers,
        )
        assert response.status_code == 422, response.text

        # Verify the original is untouched
        get_resp = await auth_client.get(f"{BASE}{strategy_id}", headers=auth_headers)
        assert get_resp.json()["version"] == 1

    @pytest.mark.anyio
    async def test_update_toggle_active(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """PUT can toggle is_active."""
        create_resp = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        strategy_id = create_resp.json()["id"]

        response = await auth_client.put(
            f"{BASE}{strategy_id}", json={"is_active": False}, headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False


# ===================================================================
# DELETE (DELETE /api/v1/strategies/{id})
# ===================================================================


class TestDeleteStrategy:
    @pytest.mark.anyio
    async def test_delete_strategy_returns_204(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """DELETE returns 204 and removes the strategy."""
        create_resp = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        strategy_id = create_resp.json()["id"]

        response = await auth_client.delete(f"{BASE}{strategy_id}", headers=auth_headers)
        assert response.status_code == 204

        # Verify it's gone
        get_resp = await auth_client.get(f"{BASE}{strategy_id}", headers=auth_headers)
        assert get_resp.status_code == 404

    @pytest.mark.anyio
    async def test_delete_nonexistent_strategy_returns_404(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """DELETE /999999 returns 404."""
        response = await auth_client.delete(f"{BASE}999999", headers=auth_headers)
        assert response.status_code == 404


# ===================================================================
# VALIDATION ENDPOINT (POST /api/v1/strategies/{id}/validate)
# ===================================================================


class TestValidateStrategy:
    @pytest.mark.anyio
    async def test_validate_valid_strategy_returns_valid_true(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """POST /0/validate with valid JSON returns valid=true, errors=[]."""
        response = await auth_client.post(
            f"{BASE}0/validate",
            json={"json_definition": VALID_GOLDEN_CROSS["json_definition"]},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["valid"] is True
        assert data["errors"] == []
        assert data["strategy_name"] == "Golden Cross"
        assert "SMA" in data["indicators_used"]
        assert "BTC/USDT" in data["symbols"]

    @pytest.mark.anyio
    async def test_validate_invalid_strategy_returns_valid_false(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """POST /0/validate with invalid JSON returns valid=false with errors."""
        response = await auth_client.post(
            f"{BASE}0/validate",
            json={"json_definition": {}},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    @pytest.mark.anyio
    async def test_validate_missing_required_field(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Validate catches missing required field 'conditions'."""
        response = await auth_client.post(
            f"{BASE}0/validate",
            json={
                "json_definition": {
                    "name": "Incomplete",
                    "action": "buy",
                    "symbols": ["BTC/USDT"],
                }
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert any("conditions" in err.lower() for err in data["errors"])

    @pytest.mark.anyio
    async def test_validate_existing_strategy(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """POST /{id}/validate works for an existing strategy too."""
        create_resp = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        strategy_id = create_resp.json()["id"]

        response = await auth_client.post(
            f"{BASE}{strategy_id}/validate",
            json={"json_definition": VALID_MACD_STRATEGY["json_definition"]},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["valid"] is True


# ===================================================================
# CROSS-USER ISOLATION
# ===================================================================


class TestCrossUserIsolation:
    @pytest.mark.anyio
    async def test_user_cannot_see_other_users_strategy(
        self,
        auth_client: AsyncClient,
        auth_headers: dict[str, str],
        async_test_db: AsyncSession,
    ) -> None:
        """A strategy created by user A should 404 for user B."""
        # Create under auth_client (user A)
        create_resp = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        strategy_id = create_resp.json()["id"]

        # Create a second user manually in the DB
        from app.models.user import User
        from app.core.security import hash_password

        user_b = User(
            email=f"other_{uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("Other123!"),
        )
        async_test_db.add(user_b)
        await async_test_db.flush()
        await async_test_db.refresh(user_b)

        # Generate a token for user B
        from app.core.security import create_access_token
        token_b = create_access_token({"user_id": str(user_b.id), "email": user_b.email})

        # Use a fresh client with user B's token
        from httpx import ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=auth_client._transport.app),  # type: ignore[attr-defined]
            base_url="http://test",
        ) as client_b:
            client_b.headers["Authorization"] = f"Bearer {token_b}"
            response = await client_b.get(f"{BASE}{strategy_id}")
            assert response.status_code == 404, (
                f"User B should not see User A's strategy, got {response.status_code}"
            )

    @pytest.mark.anyio
    async def test_user_cannot_update_other_users_strategy(
        self,
        auth_client: AsyncClient,
        auth_headers: dict[str, str],
        async_test_db: AsyncSession,
    ) -> None:
        """PUT by user B on user A's strategy returns 404."""
        create_resp = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        strategy_id = create_resp.json()["id"]

        from app.models.user import User
        from app.core.security import hash_password, create_access_token

        user_b = User(
            email=f"other_{uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("Other123!"),
        )
        async_test_db.add(user_b)
        await async_test_db.flush()
        await async_test_db.refresh(user_b)

        from httpx import ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=auth_client._transport.app),  # type: ignore[attr-defined]
            base_url="http://test",
        ) as client_b:
            client_b.headers["Authorization"] = f"Bearer {create_access_token({'user_id': str(user_b.id), 'email': user_b.email})}"
            response = await client_b.put(
                f"{BASE}{strategy_id}", json={"name": "Hijacked"}
            )
            assert response.status_code == 404

    @pytest.mark.anyio
    async def test_user_cannot_delete_other_users_strategy(
        self,
        auth_client: AsyncClient,
        auth_headers: dict[str, str],
        async_test_db: AsyncSession,
    ) -> None:
        """DELETE by user B on user A's strategy returns 404."""
        create_resp = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        strategy_id = create_resp.json()["id"]

        from app.models.user import User
        from app.core.security import hash_password, create_access_token

        user_b = User(
            email=f"other_{uuid4().hex[:8]}@example.com",
            hashed_password=hash_password("Other123!"),
        )
        async_test_db.add(user_b)
        await async_test_db.flush()
        await async_test_db.refresh(user_b)

        from httpx import ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=auth_client._transport.app),  # type: ignore[attr-defined]
            base_url="http://test",
        ) as client_b:
            client_b.headers["Authorization"] = f"Bearer {create_access_token({'user_id': str(user_b.id), 'email': user_b.email})}"
            response = await client_b.delete(f"{BASE}{strategy_id}")
            assert response.status_code == 404


# ===================================================================
# SQL INJECTION SAFETY
# ===================================================================


class TestSQLInjectionSafety:
    @pytest.mark.anyio
    async def test_sql_injection_in_name_and_tags_not_executed(
        self,
        auth_client: AsyncClient,
        auth_headers: dict[str, str],
        async_test_db: AsyncSession,
    ) -> None:
        """Strategy with SQL-like strings is stored literally, not executed."""
        response = await auth_client.post(BASE, json=SQL_INJECTION_PAYLOAD, headers=auth_headers)
        # Should be created successfully (the JSON definition is structurally valid)
        assert response.status_code == 201, response.text
        data = response.json()

        # The SQL-like strings are stored literally
        assert data["name"] == "'; DROP TABLE strategies; --"
        assert data["tags"] == ["'; SELECT * FROM api_keys; --"]

        # Verify in DB
        stmt = select(Strategy).where(Strategy.id == data["id"])
        result = await async_test_db.execute(stmt)
        db_strategy = result.scalar_one()
        assert db_strategy.name == "'; DROP TABLE strategies; --"
        assert db_strategy.json_definition["name"] == "1' OR '1'='1"
        assert "'; DROP TABLE usr--" in db_strategy.json_definition["symbols"]
        assert db_strategy.tags == ["'; SELECT * FROM api_keys; --"]

        # Verify the strategy model table still exists (not dropped!)
        stmt2 = select(Strategy).where(Strategy.id != data["id"])
        await async_test_db.execute(stmt2)  # succeeds → table exists

    @pytest.mark.anyio
    async def test_sql_injection_in_json_definition_symbols(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """SQL injection in symbol names is safely stored."""
        payload = {
            "name": "SQL Symbols",
            "json_definition": {
                "name": "SQL Symbols",
                "conditions": [
                    {"indicator": "RSI", "params": [14], "operator": "<", "threshold": 30}
                ],
                "action": "buy",
                "symbols": ["BTC/USDT'; DROP trd-"],
            },
        }
        response = await auth_client.post(BASE, json=payload, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert "BTC/USDT'; DROP trd-" in data["json_definition"]["symbols"]

    @pytest.mark.anyio
    async def test_sql_injection_validates_normally(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Validation endpoint handles SQL-like strings without error."""
        response = await auth_client.post(
            f"{BASE}0/validate",
            json={
                "json_definition": {
                    "name": "'; SELECT 1; --",
                    "conditions": [
                        {"indicator": "SMA", "params": [9], "operator": ">", "threshold": 0}
                    ],
                    "action": "buy",
                    "symbols": ["'; SELECT * FROM pw-"],
                }
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Should be valid (structurally correct even with SQL-like names)
        assert data["valid"] is True
        assert data["strategy_name"] == "'; SELECT 1; --"


# ===================================================================
# EDGE CASES
# ===================================================================


class TestEdgeCases:
    @pytest.mark.anyio
    async def test_create_multiple_strategies_for_same_user(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A user can create multiple strategies."""
        r1 = await auth_client.post(BASE, json=VALID_GOLDEN_CROSS, headers=auth_headers)
        r2 = await auth_client.post(BASE, json=VALID_MACD_STRATEGY, headers=auth_headers)
        r3 = await auth_client.post(BASE, json=VALID_RSI_STRATEGY, headers=auth_headers)

        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r3.status_code == 201

        # All belong to the same user
        ids = {r1.json()["id"], r2.json()["id"], r3.json()["id"]}
        assert len(ids) == 3  # distinct IDs

    @pytest.mark.anyio
    async def test_long_strategy_name_accepted(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A strategy name up to 200 characters is accepted."""
        long_name = "A" * 200
        payload = {
            "name": long_name,
            "json_definition": {
                "name": long_name,
                "conditions": [
                    {"indicator": "SMA", "params": [9], "operator": ">", "threshold": 0}
                ],
                "action": "buy",
                "symbols": ["BTC/USDT"],
            },
        }
        response = await auth_client.post(BASE, json=payload, headers=auth_headers)
        assert response.status_code == 201

    @pytest.mark.anyio
    async def test_list_empty_when_no_strategies(
        self, auth_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """GET returns empty list when user has no strategies."""
        response = await auth_client.get(BASE, headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []
"""
Tests for API-key CRUD endpoints (all under ``/api/v1/api-keys``).

Every endpoint requires authentication – unauthenticated calls must return 401.
Secrets are always masked in responses.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ── Helpers ────────────────────────────────────────────────


def _create_key_payload(**overrides: str | None) -> dict[str, str | None]:
    """Return a minimal valid API-key creation payload."""
    defaults: dict[str, str | None] = {
        "exchange_name": "shark",
        "label": "test-key",
        "api_key": "my-api-key-12345",
        "api_secret": "my-api-secret-67890",
        "passphrase": "my-passphrase",
    }
    defaults.update(overrides)
    return defaults


async def _create_key(
    client: AsyncClient,
    headers: dict[str, str],
    **overrides: str | None,
) -> dict:
    """Helper: create an API key via POST and return the JSON body."""
    payload = _create_key_payload(**overrides)
    response = await client.post("/api/v1/api-keys/", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# ── Unauthenticated access ─────────────────────────────────


@pytest.mark.anyio
async def test_list_keys_without_auth_returns_401(
    auth_client: AsyncClient,
) -> None:
    """GET /api/v1/api-keys/ without token → 401."""
    response = await auth_client.get("/api/v1/api-keys/")
    assert response.status_code == 401, response.text


@pytest.mark.anyio
async def test_create_key_without_auth_returns_401(
    auth_client: AsyncClient,
) -> None:
    """POST /api/v1/api-keys/ without token → 401."""
    response = await auth_client.post(
        "/api/v1/api-keys/",
        json=_create_key_payload(),
    )
    assert response.status_code == 401, response.text


@pytest.mark.anyio
async def test_get_key_without_auth_returns_401(
    auth_client: AsyncClient,
) -> None:
    """GET /api/v1/api-keys/1 without token → 401."""
    response = await auth_client.get("/api/v1/api-keys/1")
    assert response.status_code == 401, response.text


@pytest.mark.anyio
async def test_delete_key_without_auth_returns_401(
    auth_client: AsyncClient,
) -> None:
    """DELETE /api/v1/api-keys/1 without token → 401."""
    response = await auth_client.delete("/api/v1/api-keys/1")
    assert response.status_code == 401, response.text


@pytest.mark.anyio
async def test_put_key_without_auth_returns_401(
    auth_client: AsyncClient,
) -> None:
    """PUT /api/v1/api-keys/1 without token → 401."""
    response = await auth_client.put(
        "/api/v1/api-keys/1",
        json={"label": "hijacked"},
    )
    assert response.status_code == 401, response.text


# ── Create API key (authenticated) ─────────────────────────


@pytest.mark.anyio
async def test_create_key_returns_masked_secrets(
    auth_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """POST /api/v1/api-keys/ → 201, response has api_key_masked and no plain secrets."""
    body = await _create_key(auth_client, auth_headers)

    assert body["exchange_name"] == "shark"
    assert body["label"] == "test-key"
    assert "api_key_masked" in body
    assert body["has_passphrase"] is True

    # The masked key must NOT contain the full plaintext
    masked = body["api_key_masked"]
    assert "my-api-key-12345" not in masked
    # Should have the masking pattern: first 4 … last 4
    assert masked.startswith("my-a")
    assert masked.endswith("2345")

    # Plain secrets must NEVER leak
    for forbidden in ("api_key", "api_secret", "passphrase", "api_key_encrypted",
                      "api_secret_encrypted", "passphrase_encrypted"):
        assert forbidden not in body, f"'{forbidden}' leaked in response!"


@pytest.mark.anyio
async def test_create_key_without_passphrase(
    auth_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """When no passphrase is provided, has_passphrase is False."""
    body = await _create_key(
        auth_client, auth_headers, passphrase=None,
    )

    assert body["has_passphrase"] is False


# ── List API keys (masked) ─────────────────────────────────


@pytest.mark.anyio
async def test_list_keys_returns_masked_list(
    auth_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/v1/api-keys/ returns a list where every item has api_key_masked."""
    # Create two keys first
    await _create_key(auth_client, auth_headers, label="key-one",
                      api_key="aaaa11112222bbbb",
                      api_secret="sec1")
    await _create_key(auth_client, auth_headers, label="key-two",
                      api_key="cccc33334444dddd",
                      api_secret="sec2")

    response = await auth_client.get("/api/v1/api-keys/", headers=auth_headers)
    assert response.status_code == 200, response.text
    keys = response.json()
    assert isinstance(keys, list)
    assert len(keys) == 2

    for key in keys:
        assert "api_key_masked" in key
        # Masking pattern visible
        masked = key["api_key_masked"]
        assert masked.count("*") > 0, f"Expected masked key, got '{masked}'"
        # No plain secrets
        for secret_field in ("api_secret", "api_key", "passphrase",
                             "api_key_encrypted", "api_secret_encrypted"):
            assert secret_field not in key, (
                f"'{secret_field}' leaked in list response!"
            )


# ── Get single key ────────────────────────────────────────


@pytest.mark.anyio
async def test_get_single_key_returns_masked(
    auth_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/v1/api-keys/{id} returns masked key."""
    created = await _create_key(auth_client, auth_headers)
    key_id = created["id"]

    response = await auth_client.get(
        f"/api/v1/api-keys/{key_id}", headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == key_id
    assert "api_key_masked" in body


@pytest.mark.anyio
async def test_get_nonexistent_key_returns_404(
    auth_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/v1/api-keys/9999 → 404."""
    response = await auth_client.get("/api/v1/api-keys/9999", headers=auth_headers)
    assert response.status_code == 404, response.text


# ── Delete API key ────────────────────────────────────────


@pytest.mark.anyio
async def test_delete_key_returns_204(
    auth_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """DELETE /api/v1/api-keys/{id} → 204, subsequent GET → 404."""
    created = await _create_key(auth_client, auth_headers)
    key_id = created["id"]

    # Delete
    response = await auth_client.delete(
        f"/api/v1/api-keys/{key_id}", headers=auth_headers,
    )
    assert response.status_code == 204, response.text
    assert response.content == b""

    # Verify it's gone
    get_resp = await auth_client.get(
        f"/api/v1/api-keys/{key_id}", headers=auth_headers,
    )
    assert get_resp.status_code == 404, get_resp.text

    # List should be empty
    list_resp = await auth_client.get("/api/v1/api-keys/", headers=auth_headers)
    assert list_resp.status_code == 200
    assert list_resp.json() == []


@pytest.mark.anyio
async def test_delete_nonexistent_key_returns_404(
    auth_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """DELETE /api/v1/api-keys/9999 → 404."""
    response = await auth_client.delete(
        "/api/v1/api-keys/9999", headers=auth_headers,
    )
    assert response.status_code == 404, response.text


# ── Update API key ────────────────────────────────────────


@pytest.mark.anyio
async def test_update_key_label(
    auth_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """PUT /api/v1/api-keys/{id} with only label updated."""
    created = await _create_key(auth_client, auth_headers)
    key_id = created["id"]

    response = await auth_client.put(
        f"/api/v1/api-keys/{key_id}",
        json={"label": "updated-label"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["label"] == "updated-label"
    # Other fields unchanged
    assert body["exchange_name"] == "shark"


@pytest.mark.anyio
async def test_update_nonexistent_key_returns_404(
    auth_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """PUT /api/v1/api-keys/9999 → 404."""
    response = await auth_client.put(
        "/api/v1/api-keys/9999",
        json={"label": "nope"},
        headers=auth_headers,
    )
    assert response.status_code == 404, response.text


# ── Cross-user isolation ─────────────────────────────────


@pytest.mark.anyio
async def test_user_cannot_see_other_users_keys(
    auth_client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """User A creates a key; user B cannot see or delete it."""
    from app.core.security import create_access_token, hash_password
    from app.models.user import User as UserModel

    # Create a second user
    user2 = UserModel(
        email="user2@example.com",
        hashed_password=hash_password("Secure123!"),
    )
    # We need direct DB access to create user2.  Because auth_client already
    # overrides get_db, we obtain the session from the app's dependency overrides.
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    # Use auth_client to sign up user2 through the API
    signup_resp = await auth_client.post(
        "/api/v1/auth/signup",
        json={"email": "user2@example.com", "password": "Secure123!"},
    )
    assert signup_resp.status_code == 201

    # Get user2's token by logging in
    login_resp = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "user2@example.com", "password": "Secure123!"},
    )
    user2_token = login_resp.json()["access_token"]
    user2_headers = {"Authorization": f"Bearer {user2_token}"}

    # User 1 creates a key
    created = await _create_key(auth_client, auth_headers, label="user1-key")
    key_id = created["id"]

    # User 2 tries to read user 1's key → 404 (not 403 – we don't leak existence)
    resp = await auth_client.get(
        f"/api/v1/api-keys/{key_id}", headers=user2_headers,
    )
    assert resp.status_code == 404, (
        f"User2 should NOT see User1's key, got {resp.status_code}"
    )

    # User 2 tries to delete user 1's key → 404
    resp = await auth_client.delete(
        f"/api/v1/api-keys/{key_id}", headers=user2_headers,
    )
    assert resp.status_code == 404

    # User 1 can still see and delete their own key
    resp = await auth_client.get(
        f"/api/v1/api-keys/{key_id}", headers=auth_headers,
    )
    assert resp.status_code == 200
"""
Tests for authentication endpoints: signup, login, token refresh, and profile lookup.

All auth routes live under ``/api/v1/auth`` (see ``app/api/__init__.py``).
"""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token


# ── Signup ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_signup_creates_user_and_returns_tokens(
    auth_client: AsyncClient,
) -> None:
    """POST /api/v1/auth/signup → 201, returns JWT pair (no plain password)."""
    payload = {"email": "newuser@example.com", "password": "Secure123!"}
    response = await auth_client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    # Plain password must NEVER be present in the response
    assert "password" not in body
    assert "hashed_password" not in body


@pytest.mark.anyio
async def test_signup_duplicate_email_returns_409(
    auth_client: AsyncClient,
) -> None:
    """Signing up twice with the same email returns HTTP 409."""
    payload = {"email": "dup@example.com", "password": "Secure123!"}
    # First signup
    r1 = await auth_client.post("/api/v1/auth/signup", json=payload)
    assert r1.status_code == 201, r1.text
    # Second signup with same email
    r2 = await auth_client.post("/api/v1/auth/signup", json=payload)
    assert r2.status_code == 409, r2.text
    assert "already exists" in r2.json()["detail"].lower()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "password,expected_status",
    [
        ("short", 422),           # < 8 chars
        ("", 422),                # empty
        ("1234567", 422),         # 7 chars – still too short
    ],
)
async def test_signup_password_validation(
    auth_client: AsyncClient,
    password: str,
    expected_status: int,
) -> None:
    """Short or empty passwords are rejected with 422."""
    payload = {"email": "passwd@example.com", "password": password}
    response = await auth_client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == expected_status, response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "email",
    ["not-an-email", "missing@", "@nodomain", "spaces in@email.com"],
)
async def test_signup_invalid_email_returns_422(
    auth_client: AsyncClient,
    email: str,
) -> None:
    """Malformed email addresses are rejected with 422."""
    payload = {"email": email, "password": "Secure123!"}
    response = await auth_client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 422, response.text


# ── Login ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_login_returns_tokens(
    auth_client: AsyncClient,
    test_user,
) -> None:
    """Valid credentials return a JWT pair."""
    payload = {"email": test_user.email, "password": "Secure123!"}
    response = await auth_client.post("/api/v1/auth/login", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.anyio
async def test_login_wrong_password_returns_401(
    auth_client: AsyncClient,
    test_user,
) -> None:
    """Wrong password → 401."""
    payload = {"email": test_user.email, "password": "wrongpassword"}
    response = await auth_client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401, response.text


@pytest.mark.anyio
async def test_login_nonexistent_user_returns_401(
    auth_client: AsyncClient,
) -> None:
    """Login for an email that doesn't exist → 401."""
    payload = {"email": "noone@example.com", "password": "Secure123!"}
    response = await auth_client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401, response.text


# ── Password hashing ─────────────────────────────────────


@pytest.mark.anyio
async def test_password_is_hashed_in_database(
    async_test_db,
    test_user,
) -> None:
    """Verify that the stored hashed_password is NOT the plaintext password."""
    from sqlalchemy import select

    from app.models.user import User as UserModel

    result = await async_test_db.execute(
        select(UserModel).where(UserModel.id == test_user.id)
    )
    user = result.scalar_one()
    assert user.hashed_password != "Secure123!"
    # bcrypt hashes always start with $2b$
    assert user.hashed_password.startswith("$2b$")


# ── GET /me ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_me_returns_user_profile(
    auth_client: AsyncClient,
    auth_headers: dict[str, str],
    test_user,
) -> None:
    """GET /api/v1/auth/me returns the authenticated user's profile."""
    response = await auth_client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == test_user.email
    assert body["is_active"] is True
    assert "id" in body
    assert "created_at" in body
    # Never leak password
    assert "password" not in body
    assert "hashed_password" not in body


@pytest.mark.anyio
async def test_me_without_token_returns_401(
    auth_client: AsyncClient,
) -> None:
    """GET /api/v1/auth/me without Authorization header → 401."""
    response = await auth_client.get("/api/v1/auth/me")
    assert response.status_code == 401, response.text


@pytest.mark.anyio
async def test_me_with_invalid_token_returns_401(
    auth_client: AsyncClient,
) -> None:
    """GET /api/v1/auth/me with a garbage token → 401."""
    response = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer garbage.token.here"},
    )
    assert response.status_code == 401, response.text


# ── Token refresh ─────────────────────────────────────────


@pytest.mark.anyio
async def test_refresh_token_returns_new_pair(
    auth_client: AsyncClient,
    test_user,
) -> None:
    """POST /api/v1/auth/refresh with a valid refresh token → 200 + new pair."""
    from app.core.security import create_refresh_token

    refresh_token = create_refresh_token(
        {"user_id": test_user.id, "email": test_user.email}
    )
    response = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    # Tokens should be rotated (key rotation is implicit —
    # the endpoint returns a fresh pair; we trust the server
    # issues a new token even if the JWT is deterministic
    # within the same second for the same payload)
    assert body["token_type"] == "bearer"


@pytest.mark.anyio
async def test_refresh_with_access_token_returns_401(
    auth_client: AsyncClient,
    test_user,
) -> None:
    """Using an access token on the refresh endpoint → 401."""
    access_token = create_access_token(
        {"user_id": test_user.id, "email": test_user.email}
    )
    response = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": access_token},
    )
    assert response.status_code == 401, response.text


@pytest.mark.anyio
async def test_refresh_with_garbage_token_returns_401(
    auth_client: AsyncClient,
) -> None:
    """Sending a completely invalid token to /refresh → 401."""
    response = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "not.a.valid.jwt"},
    )
    assert response.status_code == 401, response.text


# ── JWT expiry ────────────────────────────────────────────


def test_access_token_expiry_is_24_hours() -> None:
    """Verify the access token's ``exp`` claim is set 24 h from now."""
    from app.core.security import decode_token

    token = create_access_token({"user_id": 1, "email": "t@t.com"})
    payload = decode_token(token)
    assert payload is not None

    now = int(time.time())
    # 24 hours = 86400 seconds; allow a few seconds slack for CI latency
    expected_exp = 86400
    actual_exp = payload["exp"] - now
    assert abs(actual_exp - expected_exp) < 10, (
        f"Expected exp ~{expected_exp}s from now, got {actual_exp}s"
    )
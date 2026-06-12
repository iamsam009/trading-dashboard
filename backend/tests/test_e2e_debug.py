"""Debug tests to isolate the 401-after-order-placement issue."""
import pytest
from httpx import AsyncClient

BASE = "/api/v1"


def _auth(headers: dict[str, str]) -> dict[str, str]:
    return {"Authorization": headers["Authorization"]}


@pytest.mark.anyio
async def test_debug_auth_after_order(
    e2e_client: AsyncClient,
    e2e_auth_headers: dict[str, str],
    mock_shark_server,
) -> None:
    """Debug: test if auth still works after placing an order."""
    headers = _auth(e2e_auth_headers)
    _base_url, _ws_url, mock_state = mock_shark_server
    mock_state.set_price("BTCINR", 50000.0)

    # Step 1: Auth works before order
    me_resp = await e2e_client.get(f"{BASE}/auth/me", headers=headers)
    print(f"\n[1] GET /auth/me -> {me_resp.status_code}")
    assert me_resp.status_code == 200, me_resp.text
    user_id = me_resp.json()["id"]
    print(f"    user_id={user_id}")

    # Step 2: Place an order
    order_payload = {
        "symbol": "BTCINR",
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": 0.01,
        "leverage": 1,
    }
    order_resp = await e2e_client.post(
        f"{BASE}/trading/manual-order",
        json=order_payload,
        headers=headers,
    )
    print(f"[2] POST /trading/manual-order -> {order_resp.status_code}")
    print(f"    body={order_resp.text[:300]}")
    assert order_resp.status_code == 201, order_resp.text

    # Step 3: Auth after order - does it still work?
    me_resp2 = await e2e_client.get(f"{BASE}/auth/me", headers=headers)
    print(f"[3] GET /auth/me (after order) -> {me_resp2.status_code}")
    print(f"    body={me_resp2.text[:300]}")
    assert me_resp2.status_code == 200, (
        f"Auth failed after order! status={me_resp2.status_code}, body={me_resp2.text}"
    )

    # Step 4: Check positions
    pos_resp = await e2e_client.get(f"{BASE}/trading/positions", headers=headers)
    print(f"[4] GET /trading/positions -> {pos_resp.status_code}")
    print(f"    body={pos_resp.text[:300]}")
    assert pos_resp.status_code == 200, pos_resp.text

    # Step 5: Place a second order
    order_payload2 = {
        "symbol": "ETHINR",
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": 0.1,
        "leverage": 1,
    }
    mock_state.set_price("ETHINR", 200000.0)
    order_resp2 = await e2e_client.post(
        f"{BASE}/trading/manual-order",
        json=order_payload2,
        headers=headers,
    )
    print(f"[5] POST /trading/manual-order (2nd) -> {order_resp2.status_code}")
    print(f"    body={order_resp2.text[:300]}")
    assert order_resp2.status_code == 201, order_resp2.text


@pytest.mark.anyio
async def test_debug_auth_basic(
    e2e_client: AsyncClient,
    e2e_auth_headers: dict[str, str],
) -> None:
    """Debug: verify basic auth works with multiple calls."""
    headers = _auth(e2e_auth_headers)

    # Multiple auth calls to ensure token is stable
    for i in range(5):
        me_resp = await e2e_client.get(f"{BASE}/auth/me", headers=headers)
        print(f"[{i}] GET /auth/me -> {me_resp.status_code}")
        assert me_resp.status_code == 200, me_resp.text
        assert me_resp.json()["email"] == e2e_auth_headers["email"]


@pytest.mark.anyio
async def test_debug_risk_settings_seed(
    e2e_client: AsyncClient,
    e2e_auth_headers: dict[str, str],
) -> None:
    """Debug: test if we can seed risk settings via the API."""
    headers = _auth(e2e_auth_headers)

    # Get current settings
    get_resp = await e2e_client.get(f"{BASE}/risk/settings", headers=headers)
    print(f"[1] GET /risk/settings -> {get_resp.status_code}")
    print(f"    body={get_resp.text[:300]}")

    # Try PUT to create settings
    put_resp = await e2e_client.put(
        f"{BASE}/risk/settings",
        json={
            "daily_loss_limit": 5000.0,
            "max_drawdown_percent": 20.0,
            "max_open_trades": 5,
            "position_size_percent": 100.0,
            "max_leverage": 10,
            "trailing_stop_enabled": False,
            "trailing_stop_distance_percent": 5.0,
            "risk_per_trade_percent": 2.0,
            "kill_switch_enabled": False,
            "trading_enabled": True,
        },
        headers=headers,
    )
    print(f"[2] PUT /risk/settings -> {put_resp.status_code}")
    print(f"    body={put_resp.text[:300]}")

    # Get again
    get_resp2 = await e2e_client.get(f"{BASE}/risk/settings", headers=headers)
    print(f"[3] GET /risk/settings (after PUT) -> {get_resp2.status_code}")
    print(f"    body={get_resp2.text[:300]}")

    # Check status
    status_resp = await e2e_client.get(f"{BASE}/risk/status", headers=headers)
    print(f"[4] GET /risk/status -> {status_resp.status_code}")
    print(f"    body={status_resp.text[:300]}")
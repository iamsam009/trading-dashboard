"""
Quick integration smoke test for Shark Exchange API credentials.

Tests connectivity and basic auth against the live Shark Exchange API.
Uses the official signing protocol:
  - GET:  sign the URL query string (params including timestamp)
  - POST: sign the JSON body (json.dumps with compact separators)
  - Headers: api-key, signature (lowercase, no X- prefix)
"""

from __future__ import annotations

import hashlib
import hmac
import time
import json
import sys
import asyncio
from urllib.parse import urlencode

# Windows consoles default to cp1252, which cannot encode emoji.
# Reconfigure stdout for UTF-8 so that whale emoji don't crash the script.
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import httpx

API_KEY = "1e012b27e8829761a4771849b8313821"
SECRET_KEY = "ed1b9dc174b032a92dd4da011065bc2d"
BASE_URL = "https://api.sharkexchange.in"


def _generate_signature(secret: str, data: str) -> str:
    """HMAC-SHA256 hex digest (official Shark Exchange helper)."""
    return hmac.new(
        secret.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _signed_headers(query_string: str) -> dict[str, str]:
    """Build auth headers for a GET request.

    Per docs: signature = HMAC-SHA256(secret, query_string)
    Headers:  api-key, signature
    """
    sig = _generate_signature(SECRET_KEY, query_string)
    return {
        "api-key": API_KEY,
        "signature": sig,
    }


# ---------------------------------------------------------------------------
# Public endpoints (no authentication required)
# ---------------------------------------------------------------------------

async def test_public_endpoints(client: httpx.AsyncClient) -> dict[str, bool]:
    """Hit public /v1/market/* and /v1/exchange/* endpoints."""
    results: dict[str, bool] = {}

    # 1. 24hr ticker for BTCINR
    try:
        url = f"{BASE_URL}/v1/market/ticker24Hr/BTCINR"
        r = await client.get(url)
        results["GET /v1/market/ticker24Hr/BTCINR"] = r.status_code == 200
        print(f"  GET /v1/market/ticker24Hr/BTCINR  -> {r.status_code}  {r.text[:150]}")
    except Exception as e:
        results["GET /v1/market/ticker24Hr/BTCINR"] = False
        print(f"  GET /v1/market/ticker24Hr/BTCINR  -> ERROR: {e}")

    # 2. Klines (candlestick data) - POST with JSON body, public
    #    Returns 201 Created (not 200) per Shark API
    try:
        url = f"{BASE_URL}/v1/market/klines?priceType=MARK_PRICE"
        body = {"pair": "BTCINR", "interval": "1m", "limit": 5}
        r = await client.post(url, json=body)
        results["POST /v1/market/klines"] = r.status_code in (200, 201)
        print(f"  POST /v1/market/klines           -> {r.status_code}  {r.text[:150]}")
    except Exception as e:
        results["POST /v1/market/klines"] = False
        print(f"  POST /v1/market/klines           -> ERROR: {e}")

    # 3. Exchange info – no auth needed per Python example in docs
    try:
        url = f"{BASE_URL}/v1/exchange/exchangeInfo"
        r = await client.get(url)
        results["GET /v1/exchange/exchangeInfo"] = r.status_code == 200
        print(f"  GET /v1/exchange/exchangeInfo     -> {r.status_code}  {r.text[:150]}")
    except Exception as e:
        results["GET /v1/exchange/exchangeInfo"] = False
        print(f"  GET /v1/exchange/exchangeInfo     -> ERROR: {e}")

    return results


# ---------------------------------------------------------------------------
# Authenticated endpoints (require api-key + signature headers)
# ---------------------------------------------------------------------------

async def test_authenticated_endpoints(client: httpx.AsyncClient) -> dict[str, bool]:
    """Hit endpoints that require HMAC-SHA256 signature auth."""
    results: dict[str, bool] = {}

    ts = str(int(time.time() * 1000))

    # 1. Open orders
    #    Doc: params = f"timestamp={timestamp}"  → sign the query string
    try:
        qs = f"timestamp={ts}"
        headers = _signed_headers(qs)
        url = f"{BASE_URL}/v1/order/open-orders?{qs}"
        r = await client.get(url, headers=headers)
        results["GET /v1/order/open-orders"] = r.status_code == 200
        print(f"  GET /v1/order/open-orders        -> {r.status_code}  {r.text[:200]}")
    except Exception as e:
        results["GET /v1/order/open-orders"] = False
        print(f"  GET /v1/order/open-orders        -> ERROR: {e}")

    # 2. Futures wallet details
    #    Doc: uses getRequest with optional marginAsset param
    try:
        qs = f"timestamp={ts}"
        headers = _signed_headers(qs)
        url = f"{BASE_URL}/v1/wallet/futures-wallet/details?{qs}"
        r = await client.get(url, headers=headers)
        results["GET /v1/wallet/futures-wallet/details"] = r.status_code == 200
        print(f"  GET /v1/wallet/futures-wallet/details -> {r.status_code}  {r.text[:200]}")
    except Exception as e:
        results["GET /v1/wallet/futures-wallet/details"] = False
        print(f"  GET /v1/wallet/futures-wallet/details -> ERROR: {e}")

    # 3. Order history (page 1)
    try:
        qs = f"timestamp={ts}&page=1&size=5"
        headers = _signed_headers(qs)
        url = f"{BASE_URL}/v1/order/order-history?{qs}"
        r = await client.get(url, headers=headers)
        results["GET /v1/order/order-history"] = r.status_code == 200
        print(f"  GET /v1/order/order-history      -> {r.status_code}  {r.text[:200]}")
    except Exception as e:
        results["GET /v1/order/order-history"] = False
        print(f"  GET /v1/order/order-history      -> ERROR: {e}")

    return results


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def main() -> int:
    print("=" * 60)
    print("\U0001f40b Shark Exchange API — Connectivity Test")
    print(f"   BASE_URL: {BASE_URL}")
    print(f"   API_KEY:  {API_KEY[:8]}...{API_KEY[-4:]}")
    print("=" * 60)

    timeout = httpx.Timeout(15.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:

        print("\n\U0001f4e1 Public Endpoints (no auth):")
        public = await test_public_endpoints(client)

        print("\n\U0001f510 Authenticated Endpoints:")
        auth = await test_authenticated_endpoints(client)

        all_results = {**public, **auth}

    print("\n" + "=" * 60)
    passed = sum(1 for v in all_results.values() if v)
    total = len(all_results)
    print(f"   Results: {passed}/{total} passed")

    for name, ok in all_results.items():
        status = "\u2705" if ok else "\u274c"
        print(f"   {status}  {name}")

    print("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
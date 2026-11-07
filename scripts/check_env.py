"""Check that the GHL token in .env reads the Kestrel sub-account.

Prints the sub-account name and its users. Never prints the token.
"""

import sys
from pathlib import Path

import httpx

# Scripts run as files (python scripts/x.py), so the repo root is not on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GHL_BASE_URL, ConfigError, env, ghl_headers

TIMEOUT = 15


def ghl_get(path: str, params: dict | None = None) -> dict:
    resp = httpx.get(
        f"{GHL_BASE_URL}{path}",
        params=params,
        headers=ghl_headers(),
        timeout=TIMEOUT,
    )
    if resp.status_code == 401:
        raise RuntimeError("401: the token is wrong or expired. Check GHL_TOKEN.")
    if resp.status_code == 403:
        raise RuntimeError(f"403 on {path}: the token is missing a scope.")
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} on {path}: {resp.text[:200]}")
    return resp.json()


def main() -> int:
    try:
        location_id = env("GHL_LOCATION_ID")
        location = ghl_get(f"/locations/{location_id}")["location"]
        users = ghl_get("/users/", {"locationId": location_id})["users"]
    except (ConfigError, RuntimeError, httpx.HTTPError, KeyError) as exc:
        print(f"ghl FAILED: {exc}")
        return 1
    print(f"sub-account: {location['name']} (timezone {location.get('timezone')})")
    print(f"users: {len(users)}")
    for user in users:
        print(f"  - {user.get('name')} ({user.get('roles', {}).get('role')})")
    return 0 if users else 1


if __name__ == "__main__":
    sys.exit(main())

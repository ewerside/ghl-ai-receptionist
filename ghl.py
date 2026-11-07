"""Small GoHighLevel API v2 client: one request function with retry on rate limits."""

import time

import httpx

from config import GHL_BASE_URL, ghl_headers

TIMEOUT = 20
MAX_TRIES = 5


class GHLError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def request(method: str, path: str, **kwargs) -> dict:
    """Call the API and return the JSON body.

    Retries 429 and 5xx with exponential backoff (1, 2, 4, 8 s), or the Retry-After header
    when GHL sends one. The sandbox allows 25 requests per 10 seconds.
    """
    for attempt in range(MAX_TRIES):
        resp = httpx.request(
            method,
            f"{GHL_BASE_URL}{path}",
            headers=ghl_headers(),
            timeout=TIMEOUT,
            **kwargs,
        )
        retryable = resp.status_code == 429 or resp.status_code >= 500
        if retryable and attempt < MAX_TRIES - 1:
            time.sleep(float(resp.headers.get("retry-after") or 2**attempt))
            continue
        if resp.status_code >= 400:
            raise GHLError(
                resp.status_code,
                f"{method} {path}: HTTP {resp.status_code}: {resp.text[:300]}",
            )
        return resp.json() if resp.content else {}
    raise AssertionError("unreachable")

"""Settings read from the environment (.env), in one place."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# GoHighLevel API v2. Checked in the official docs on 2026-11-07.
GHL_BASE_URL = "https://services.leadconnectorhq.com"
GHL_VERSION = "2021-07-28"

DEFAULTS = {
    "LLM_MODEL": "claude-haiku-5-5",
    "EVAL_MODEL": "claude-sonnet-5-5",
}


class ConfigError(RuntimeError):
    pass


def env(name: str) -> str:
    """Return a required setting, or fail naming the missing variable."""
    value = os.getenv(name, "").strip() or DEFAULTS.get(name, "")
    if not value:
        raise ConfigError(
            f"{name} is not set. Add it to .env (names are in .env.example)."
        )
    return value


def ghl_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {env('GHL_TOKEN')}",
        "Version": GHL_VERSION,
        "Accept": "application/json",
    }

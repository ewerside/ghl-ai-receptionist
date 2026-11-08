"""Settings read from the environment (.env), in one place."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
load_dotenv(ROOT / ".env")

# GoHighLevel API v2. Checked in the official docs on 2026-11-07.
GHL_BASE_URL = "https://services.leadconnectorhq.com"
GHL_VERSION = "2021-07-28"

DEFAULTS = {
    "LLM_MODEL": "claude-sonnet-5-5",
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


def n8n_base_url() -> str:
    url = env("N8N_BASE_URL").rstrip("/")
    # GHL and the test scripts call the webhook from outside the server.
    if not url.startswith("https://"):
        raise ConfigError("N8N_BASE_URL must start with https://")
    return url


def ghl_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {env('GHL_TOKEN')}",
        "Version": GHL_VERSION,
        "Accept": "application/json",
    }

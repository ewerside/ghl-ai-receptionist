"""Export the live workflows back to n8n/, with markers in place of ids and secrets.

Use it after editing a workflow in the n8n editor. It writes nothing if a secret
would end up in the JSON.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

# Make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deploy_n8n import checked, find_workflow, marker_values

from config import ROOT, ConfigError, env, n8n_base_url

N8N_DIR = ROOT / "n8n"
WORKFLOWS = {
    "receptionist errors": "errors.json",
    "receptionist inbound message": "inbound-message.json",
}


def replacements(values: dict[str, str]) -> list[tuple[str, str]]:
    """(text as it appears in the exported JSON, marker). Short values keep context."""
    swaps = []
    for key, value in values.items():
        escaped = json.dumps(value)[1:-1]
        if key.startswith("CRED_") or key == "ERROR_WORKFLOW_ID":
            swaps.append((f'"{escaped}"', '"{{' + key + '}}"'))
        elif key == "LLM_MODEL":
            # The model name also appears in the list of allowed models; only swap the default.
            swaps.append(
                (f"DEFAULT_MODEL = '{escaped}'", "DEFAULT_MODEL = '{{LLM_MODEL}}'")
            )
        else:
            swaps.append((escaped, "{{" + key + "}}"))
    return swaps


def secrets_in(text: str) -> list[str]:
    db_password = urlsplit(env("DATABASE_URL")).password or "no-password"
    patterns = [
        "pit-",
        "sk-ant",
        "eyJ",
        env("GHL_TOKEN"),
        env("ANTHROPIC_API_KEY"),
        env("N8N_API_KEY"),
        env("INBOUND_TOKEN"),
        db_password,
        env("GHL_LOCATION_ID"),
    ]
    return [p if len(p) < 12 else p[:4] + "..." for p in patterns if p in text]


def main() -> int:
    exports = {}
    try:
        values = marker_values()
        headers = {"X-N8N-API-KEY": env("N8N_API_KEY")}
        with httpx.Client(
            base_url=f"{n8n_base_url()}/api/v1", headers=headers, timeout=30
        ) as client:
            ids = {name: find_workflow(client, name) for name in WORKFLOWS}
            missing = [name for name, wf_id in ids.items() if not wf_id]
            if missing:
                raise RuntimeError(f"not found on n8n: {', '.join(missing)}")
            values["ERROR_WORKFLOW_ID"] = ids["receptionist errors"]
            swaps = replacements(values)
            for name, filename in WORKFLOWS.items():
                live = checked(client.get(f"/workflows/{ids[name]}")).json()
                keep = {
                    k: live[k] for k in ("name", "nodes", "connections", "settings")
                }
                keep["settings"] = {
                    k: v
                    for k, v in keep["settings"].items()
                    if k
                    in ("executionOrder", "errorWorkflow", "saveDataErrorExecution")
                }
                text = json.dumps(keep, indent=2, ensure_ascii=False)
                for value, marker in swaps:
                    text = text.replace(value, marker)
                exports[filename] = text
    except (ConfigError, RuntimeError, httpx.HTTPError) as exc:
        print(f"export_n8n FAILED: {exc}")
        return 1
    # Check before writing: a leaked file in n8n/ is one commit away from the public repo.
    leaks = [f"{f}: {p}" for f, text in exports.items() for p in secrets_in(text)]
    if leaks:
        print("secret found, nothing written: " + "; ".join(leaks))
        return 1
    for filename, text in exports.items():
        (N8N_DIR / filename).write_text(text + "\n", encoding="utf-8")
        print(f"exported n8n/{filename}")
    print("secret check passed: no token, key or location id in the export")
    return 0


if __name__ == "__main__":
    sys.exit(main())

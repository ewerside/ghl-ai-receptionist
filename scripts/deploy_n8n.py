"""Publish the workflows in n8n/ with real ids and secrets filled in.

The JSON in the repo has markers like {{CRED_GHL}}. They are filled in memory and
sent to the n8n API; the filled JSON is never written to disk.
"""

import json
import re
import sys
from pathlib import Path

import httpx

# Make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CONFIG_DIR, ROOT, ConfigError, env, n8n_base_url

# The error workflow goes first so the main workflow can point to its id.
WORKFLOWS = ["errors.json", "inbound-message.json"]
MARKER = re.compile(r"\{\{[A-Z0-9_]+\}\}")


def checked(resp: httpx.Response) -> httpx.Response:
    if resp.status_code >= 400:
        raise RuntimeError(
            f"{resp.request.method} {resp.request.url.path} answered "
            f"{resp.status_code}: {resp.text[:300]}"
        )
    return resp


def marker_values() -> dict[str, str]:
    try:
        ids = json.loads((CONFIG_DIR / "ghl_ids.json").read_text(encoding="utf-8"))
        creds = json.loads((CONFIG_DIR / "n8n.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"{exc.filename} is missing. Run setup_ghl.py and setup_n8n.py first."
        ) from None
    creds = creds["credentials"]
    return {
        "GHL_IDS_JSON": json.dumps(ids, separators=(",", ":")),
        "LLM_MODEL": env("LLM_MODEL"),
        "EMBED_URL": env("EMBED_URL"),
        "N8N_BASE_URL": n8n_base_url(),
        "CRED_GHL": creds["ghl"]["id"],
        "CRED_ANTHROPIC": creds["anthropic"]["id"],
        "CRED_SUPABASE": creds["supabase"]["id"],
        "CRED_INBOUND": creds["inbound"]["id"],
        "CRED_N8N": creds["n8n"]["id"],
    }


def fill(text: str, values: dict[str, str]) -> dict:
    for key, value in values.items():
        # Values land inside JSON strings, so escape them the way JSON would.
        text = text.replace("{{" + key + "}}", json.dumps(value)[1:-1])
    missing = sorted(set(MARKER.findall(text)))
    if missing:
        raise RuntimeError(f"no value for {', '.join(missing)}")
    return json.loads(text)


def find_workflow(client: httpx.Client, name: str) -> str | None:
    ids, cursor = [], None
    while True:
        params = {"limit": 100, **({"cursor": cursor} if cursor else {})}
        body = checked(client.get("/workflows", params=params)).json()
        ids += [w["id"] for w in body["data"] if w["name"] == name]
        cursor = body.get("nextCursor")
        if not cursor:
            break
    if len(ids) > 1:
        raise RuntimeError(f"{len(ids)} workflows are named '{name}'. Keep one.")
    return ids[0] if ids else None


def publish(client: httpx.Client, workflow: dict) -> str:
    body = {k: workflow[k] for k in ("name", "nodes", "connections", "settings")}
    wf_id = find_workflow(client, workflow["name"])
    if wf_id:
        checked(client.put(f"/workflows/{wf_id}", json=body))
        status = "updated"
    else:
        wf_id = checked(client.post("/workflows", json=body)).json()["id"]
        status = "created"
    # In n8n 2.x the error workflow also has to be active, or it never runs.
    checked(client.post(f"/workflows/{wf_id}/activate"))
    status += ", active"
    print(f"{workflow['name']}: {status} ({wf_id})")
    return wf_id


def main() -> int:
    try:
        base = n8n_base_url()
        values = marker_values()
        headers = {"X-N8N-API-KEY": env("N8N_API_KEY")}
        with httpx.Client(
            base_url=f"{base}/api/v1", headers=headers, timeout=30
        ) as client:
            for filename in WORKFLOWS:
                text = (ROOT / "n8n" / filename).read_text(encoding="utf-8")
                wf_id = publish(client, fill(text, values))
                if filename == "errors.json":
                    values["ERROR_WORKFLOW_ID"] = wf_id
    except (ConfigError, RuntimeError, httpx.HTTPError) as exc:
        print(f"deploy_n8n FAILED: {exc}")
        return 1
    print(f"webhook: {base}/webhook/ghl-inbound")
    return 0


if __name__ == "__main__":
    sys.exit(main())

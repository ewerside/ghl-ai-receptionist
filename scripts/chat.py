"""Play a test conversation as the customer: each message goes into GHL, then to the n8n webhook.

This is what the GHL web chat plus a workflow webhook would do. Doing it from a script keeps
the test runs repeatable.

python scripts/chat.py c01 c05        play conversations from data/conversations.jsonl
python scripts/chat.py --smoke        play 5 conversations, one per key situation, and check them
"""

import csv
import json
import sys
import time
from pathlib import Path

import httpx

# Make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ghl
from config import CONFIG_DIR, ROOT, ConfigError, env, n8n_base_url

DATA = ROOT / "data"
# One conversation per key situation from the business rule table.
SMOKE = {
    "emergency": "Booked",
    "install_owner": "Booked",
    "out_of_area": "Lost",
    "handoff": "Needs Human",
    "question": "New Lead",
}


def load_ids() -> dict:
    return json.loads((CONFIG_DIR / "ghl_ids.json").read_text(encoding="utf-8"))


def load_conversations() -> dict[str, dict]:
    lines = (DATA / "conversations.jsonl").read_text(encoding="utf-8").splitlines()
    return {c["id"]: c for c in map(json.loads, lines)}


def load_expected() -> dict[str, dict]:
    with (DATA / "expected.csv").open(encoding="utf-8") as f:
        return {row["id"]: row for row in csv.DictReader(f)}


def upsert_contact(ids: dict, contact: dict) -> str:
    body = {
        **contact,
        "locationId": ids["location_id"],
        "tags": ["ai-test"],
        "source": "web chat (test)",
    }
    return ghl.request("POST", "/contacts/upsert", json=body)["contact"]["id"]


def send_message(ids: dict, contact_id: str, text: str, model: str | None) -> dict:
    """Store the customer message in GHL, then hand it to n8n. Returns the n8n answer."""
    stored = ghl.request(
        "POST",
        "/conversations/messages/inbound",
        json={
            "type": "Live_Chat",
            "contactId": contact_id,
            "message": text,
            "direction": "inbound",
        },
    )
    payload = {
        "message_id": stored["messageId"],
        "conversation_id": stored["conversationId"],
        "contact_id": contact_id,
        "body": text,
    }
    if model:
        payload["model"] = model
    started = time.monotonic()
    resp = httpx.post(
        f"{n8n_base_url()}/webhook/ghl-inbound",
        json=payload,
        headers={"X-Inbound-Token": env("INBOUND_TOKEN")},
        timeout=120,
    )
    answer = (
        resp.json()
        if resp.content
        and resp.headers.get("content-type", "").startswith("application/json")
        else {"raw": resp.text[:300]}
    )
    return {
        "http": resp.status_code,
        "seconds": round(time.monotonic() - started, 1),
        **payload,
        **answer,
    }


def play(conv: dict, model: str | None = None, verbose: bool = True) -> dict:
    ids = load_ids()
    contact_id = upsert_contact(ids, conv["contact"])
    turns = []
    for text in conv["messages"]:
        turn = send_message(ids, contact_id, text, model)
        turns.append(turn)
        if verbose:
            print(f"  customer: {text}")
            print(
                f"  agent ({turn.get('outcome')}, {turn.get('stage')}, {turn['seconds']} s): {turn.get('reply', turn)}"
            )
        if turn["http"] != 200:
            break
    return {"id": conv["id"], "contact_id": contact_id, "turns": turns}


def final_state(ids: dict, contact_id: str) -> dict:
    opps = ghl.request(
        "GET",
        "/opportunities/search",
        params={
            "location_id": ids["location_id"],
            "contact_id": contact_id,
            "pipeline_id": ids["pipeline"]["id"],
        },
    )["opportunities"]
    stage_names = {v: k for k, v in ids["pipeline"]["stages"].items()}
    stage = stage_names.get(opps[0]["pipelineStageId"]) if opps else None
    contact = ghl.request("GET", f"/contacts/{contact_id}")["contact"]
    by_id = {f["id"]: f.get("value") for f in contact.get("customFields", [])}
    fields = {k: by_id.get(v) for k, v in ids["fields"].items()}
    return {"stage": stage, "fields": fields, "tags": contact.get("tags", [])}


def smoke() -> int:
    convs, expected, ids = load_conversations(), load_expected(), load_ids()
    failures = 0
    for situation, want_stage in SMOKE.items():
        conv_id = next(
            i
            for i, row in expected.items()
            if row["situation"] == situation and row["final_stage"] == want_stage
        )
        print(f"{conv_id} ({situation})")
        result = play(convs[conv_id])
        state = final_state(ids, result["contact_id"])
        filled = [
            k
            for k in ("ai_score", "ai_tier", "ai_intent", "ai_reason")
            if state["fields"].get(k) not in (None, "")
        ]
        ok = state["stage"] == want_stage and len(filled) == 4
        failures += not ok
        print(
            f"  -> stage {state['stage']} (want {want_stage}), fields {state['fields']}, tags {state['tags']}: {'ok' if ok else 'FAIL'}\n"
        )
    print("smoke test passed" if not failures else f"{failures} of {len(SMOKE)} failed")
    return 1 if failures else 0


def main(args: list[str]) -> int:
    try:
        if args == ["--smoke"]:
            return smoke()
        convs = load_conversations()
        for conv_id in args:
            print(conv_id)
            play(convs[conv_id])
    except (ConfigError, ghl.GHLError, httpx.HTTPError, KeyError) as exc:
        print(f"chat FAILED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

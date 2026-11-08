"""Four failure tests against the live flow. Results go to data/reliability.json for the report.

1. Invalid Claude key: the fixed rule answers and the conversation goes to a person.
2. GHL answers with errors: the event goes to failed_events and the replay finishes it.
3. The offered time is taken before the customer confirms: the agent offers the next one.
4. The same message arrives twice at the same moment: one reply only.

Credentials are broken and restored through the n8n API; the restore runs even if a test fails.
"""

import json
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import psycopg

# Scripts run as files (python scripts/x.py), so the repo root is not on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chat
import replay_failed
import setup_n8n

import ghl
from config import CONFIG_DIR, ROOT, ConfigError, env, n8n_base_url

OUT = ROOT / "data" / "reliability.json"


def contact(n: int) -> dict:
    return {
        "firstName": "Reliability",
        "lastName": f"Test {n}",
        "email": f"reliability.test{n}@mail.example.com",
        "phone": f"+1512555{150 + n:04d}",
    }


def patch_credential(key: str, data: dict) -> None:
    cred = json.loads((CONFIG_DIR / "n8n.json").read_text(encoding="utf-8"))[
        "credentials"
    ][key]
    resp = httpx.patch(
        f"{n8n_base_url()}/api/v1/credentials/{cred['id']}",
        headers={"X-N8N-API-KEY": env("N8N_API_KEY")},
        json={"name": cred["name"], "type": "httpHeaderAuth", "data": data},
        timeout=20,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"could not patch credential {key}: {resp.status_code} {resp.text[:200]}"
        )


def restore_credentials() -> None:
    if setup_n8n.main() != 0:
        raise RuntimeError("could not restore the n8n credentials")


def outbound_count(conversation_id: str, since: float) -> int:
    """Chat replies sent to the customer since the test started (GHL also logs activity
    entries like "Opportunity created" as outbound messages, so those are skipped)."""
    msgs = ghl.request(
        "GET", f"/conversations/{conversation_id}/messages", params={"limit": 50}
    )
    return sum(
        m.get("direction") == "outbound"
        and m.get("messageType") == "TYPE_LIVE_CHAT"
        and datetime.fromisoformat(m["dateAdded"]).timestamp() >= since
        for m in msgs["messages"]["messages"]
    )


def log_row(message_id: str) -> dict:
    with psycopg.connect(env("DATABASE_URL"), connect_timeout=15) as conn:
        cur = conn.execute(
            "select status, used_fallback, next_action, reply from message_log where message_id = %s",
            (message_id,),
        )
        row = cur.fetchone()
    return (
        dict(zip(["status", "used_fallback", "next_action", "reply"], row))
        if row
        else {}
    )


def test_bad_claude_key(ids: dict) -> dict:
    started = time.time() - 2
    cid = chat.upsert_contact(ids, contact(1))
    patch_credential(
        "anthropic",
        setup_n8n.header_auth(
            "x-api-key", "sk-invalid-key-for-test", "api.anthropic.com"
        ),
    )
    try:
        turn = chat.send_message(
            ids,
            cid,
            "My AC stopped working and it's 98 degrees. I own my home in 78745.",
            None,
        )
    finally:
        restore_credentials()
    time.sleep(10)
    state = chat.final_state(ids, cid)
    log = log_row(turn["message_id"])
    replies = outbound_count(turn["conversation_id"], started)
    ok = (
        turn.get("used_fallback") is True
        and turn.get("outcome") == "handoff"
        and state["stage"] == "Needs Human"
        and "needs-human" in state["tags"]
        and replies == 1
    )
    return {
        "test": "Invalid Claude API key",
        "expected": "fixed rule scores the lead, one reply, task for a person, card in Needs Human",
        "result": f"used_fallback={turn.get('used_fallback')}, outcome {turn.get('outcome')}, stage {state['stage']}, "
        f"score {state['fields'].get('ai_score')} ({state['fields'].get('ai_tier')}), replies sent {replies}",
        "lost": 0 if log.get("status") == "done" else 1,
        "duplicate_replies": max(0, replies - 1),
        "pass": ok,
    }


def test_ghl_errors(ids: dict) -> dict:
    started = time.time() - 2
    cid = chat.upsert_contact(ids, contact(2))
    patch_credential(
        "ghl",
        setup_n8n.header_auth(
            "Authorization",
            "Bearer pit-invalid-token-for-test",
            "services.leadconnectorhq.com",
        ),
    )
    try:
        turn = chat.send_message(ids, cid, "How much is a tune-up?", None)
    finally:
        restore_credentials()
    time.sleep(10)
    before = log_row(turn["message_id"])
    with psycopg.connect(env("DATABASE_URL"), connect_timeout=15) as conn:
        queued = conn.execute(
            "select count(*) from failed_events where payload->>'message_id' = %s and replayed_at is null",
            (turn["message_id"],),
        ).fetchone()[0]
    replay_failed.main([])
    time.sleep(5)
    after = log_row(turn["message_id"])
    replies = outbound_count(turn["conversation_id"], started)
    with psycopg.connect(env("DATABASE_URL"), connect_timeout=15) as conn:
        left = conn.execute(
            "select count(*) from failed_events where payload->>'message_id' = %s and replayed_at is null",
            (turn["message_id"],),
        ).fetchone()[0]
    ok = (
        before.get("status") == "failed"
        and queued == 1
        and after.get("status") == "done"
        and left == 0
        and replies == 1
    )
    return {
        "test": "GHL API answers with errors (invalid token)",
        "expected": "event saved to failed_events, replay finishes it, one reply",
        "result": f"first run: status {before.get('status')}, {queued} event queued; after replay: status {after.get('status')}, "
        f"{left} left in queue, replies sent {replies}",
        "lost": 0 if after.get("status") == "done" else 1,
        "duplicate_replies": max(0, replies - 1),
        "pass": ok,
    }


def test_slot_taken(ids: dict) -> dict:
    started = time.time() - 2
    cid = chat.upsert_contact(ids, contact(3))
    first = chat.send_message(
        ids, cid, "My AC is making a loud buzzing noise. I own my home in 78745.", None
    )
    sent = 1
    if first.get("outcome") != "offer_slots":
        first = chat.send_message(
            ids, cid, "Can you come this week? Any time works.", None
        )
        sent += 1
    now = int(time.time() * 1000)
    free = ghl.request(
        "GET",
        f"/calendars/{ids['calendar_id']}/free-slots",
        params={
            "startDate": now,
            "endDate": now + 8 * 86_400_000,
            "timezone": "America/Chicago",
        },
    )
    slots = sorted(
        s for v in free.values() if isinstance(v, dict) for s in v.get("slots", [])
    )
    taken = slots[0]
    # Someone else books the first offered time before the customer answers.
    blocker = chat.upsert_contact(ids, contact(4))
    end = (datetime.fromisoformat(taken) + timedelta(hours=2)).isoformat()
    ghl.request(
        "POST",
        "/calendars/events/appointments",
        json={
            "calendarId": ids["calendar_id"],
            "locationId": ids["location_id"],
            "contactId": blocker,
            "startTime": taken,
            "endTime": end,
            "title": "Blocker for the reliability test",
            "appointmentStatus": "confirmed",
        },
    )
    second = chat.send_message(
        ids, cid, "The first time works for me, please book it.", None
    )
    sent += 1
    time.sleep(5)
    events = ghl.request(
        "GET",
        "/calendars/events",
        params={
            "locationId": ids["location_id"],
            "calendarId": ids["calendar_id"],
            "startTime": now - 86_400_000,
            "endTime": now + 14 * 86_400_000,
        },
    )["events"]
    at_taken = [e for e in events if e["startTime"] == taken]
    mine = [e for e in events if e.get("contactId") == cid]
    replies = outbound_count(second["conversation_id"], started)
    ok = (
        second.get("outcome") in ("slot_taken", "offer_slots")
        and len(at_taken) == 1
        and not mine
    )
    return {
        "test": "Offered time taken before the customer confirms",
        "expected": "no booking on the taken time, the agent offers the next open time",
        "result": f"first turn {first.get('outcome')}; after the time was taken: {second.get('outcome')}, "
        f"events at {taken[11:16]}: {len(at_taken)}, events for this customer: {len(mine)}. Reply: {second.get('reply')}",
        "lost": 0,
        "duplicate_replies": max(0, replies - sent),
        "pass": ok,
    }


def test_duplicate_delivery(ids: dict) -> dict:
    started = time.time() - 2
    cid = chat.upsert_contact(ids, contact(5))
    stored = ghl.request(
        "POST",
        "/conversations/messages/inbound",
        json={
            "type": "Live_Chat",
            "contactId": cid,
            "message": "What warranty do you give on repairs?",
            "direction": "inbound",
        },
    )
    payload = {
        "message_id": stored["messageId"],
        "conversation_id": stored["conversationId"],
        "contact_id": cid,
        "body": "What warranty do you give on repairs?",
    }
    answers = []

    def post() -> None:
        resp = httpx.post(
            f"{n8n_base_url()}/webhook/ghl-inbound",
            json=payload,
            headers={"X-Inbound-Token": env("INBOUND_TOKEN")},
            timeout=120,
        )
        answers.append(
            resp.json().get("status") if resp.content else f"HTTP {resp.status_code}"
        )

    # The same delivery twice at the same moment, as a webhook retry would do.
    threads = [threading.Thread(target=post) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    time.sleep(5)
    replies = outbound_count(stored["conversationId"], started)
    ok = sorted(answers) == ["done", "duplicate"] and replies == 1
    return {
        "test": "Same message delivered twice at the same moment",
        "expected": "one run answers, the other stops as duplicate, one reply",
        "result": f"answers {sorted(answers)}, replies sent {replies}",
        "lost": 0 if "done" in answers else 1,
        "duplicate_replies": max(0, replies - 1),
        "pass": ok,
    }


def main() -> int:
    results = []
    try:
        ids = chat.load_ids()
        for test in (
            test_bad_claude_key,
            test_ghl_errors,
            test_slot_taken,
            test_duplicate_delivery,
        ):
            print(f"running {test.__name__}")
            result = test(ids)
            print(f"  {'PASS' if result['pass'] else 'FAIL'}: {result['result']}")
            results.append(result)
    except (
        ConfigError,
        RuntimeError,
        ghl.GHLError,
        httpx.HTTPError,
        psycopg.Error,
    ) as exc:
        print(f"reliability test FAILED: {exc}")
        return 1
    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    lost = sum(r["lost"] for r in results)
    dupes = sum(r["duplicate_replies"] for r in results)
    print(
        f"{sum(r['pass'] for r in results)} of {len(results)} passed, {lost} lost messages, {dupes} duplicate replies"
    )
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

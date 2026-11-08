"""Run the 50 test conversations through the live flow, once per model, and judge the replies.

python scripts/run_eval.py                       both models, demo reset before each run
python scripts/run_eval.py --model claude-haiku-5-5
python scripts/run_eval.py --judge claude-haiku-5-5   only judge an existing run

Writes data/runs/<model>.jsonl (one line per conversation), <model>-calendar.json and
<model>-judge.jsonl. scripts/report.py turns them into docs/report.md.
"""

import csv
import json
import random
import sys
import time
from pathlib import Path

import anthropic
import httpx
import psycopg

# Make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chat
import reset_demo

import ghl
from config import ROOT, ConfigError, env

MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5"]
RUNS = ROOT / "data" / "runs"
JUDGE_MODEL = "claude-sonnet-5-5"
SEED = 42

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["unsupported_claims"],
    "properties": {
        "unsupported_claims": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Each business fact in the reply that the help center does not support.",
        }
    },
}

JUDGE_PROMPT = """You check replies written by a chat receptionist for Kestrel Air & Plumbing against the company's help center, which is below.

List every business fact in the reply that the help center does not support: prices, fees, discounts, hours, service areas, policies, warranties, financing terms, durations, what is included, promises about response times. A fact is supported if the help center states it, even in other words.

Do not list:
- visit days and times offered or booked (they come from the live calendar),
- things the customer said about themselves,
- greetings, empathy, questions, or saying that a team member will follow up,
- general advice that is common sense and not a company policy (for example "close the blinds").

Return an empty list when every business fact is supported.

<help_center>
{kb}
</help_center>"""


def kb_text() -> str:
    parts = []
    for path in sorted((ROOT / "kb" / "articles").glob("*.md")):
        parts.append(
            f'<article id="{path.stem}">\n{path.read_text(encoding="utf-8")}\n</article>'
        )
    return "\n".join(parts)


def log_rows(message_ids: list[str]) -> dict[str, dict]:
    with psycopg.connect(env("DATABASE_URL"), connect_timeout=15) as conn:
        cur = conn.execute(
            "select message_id, intent, tier, score, next_action, used_fallback, error, articles, "
            "input_tokens, output_tokens, cost_usd, latency_ms, status "
            "from message_log where message_id = any(%s)",
            (message_ids,),
        )
        cols = [c.name for c in cur.description]
        return {
            r[0]: {**dict(zip(cols, r)), "cost_usd": float(r[10] or 0)}
            for r in cur.fetchall()
        }


def calendar_events(ids: dict) -> list[dict]:
    now = int(time.time() * 1000)
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
    return [
        {"id": e["id"], "contactId": e.get("contactId"), "startTime": e["startTime"]}
        for e in events
    ]


def run(model: str, only: list[str] | None) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    print(f"== {model}: resetting demo data")
    reset_demo.main([])
    ids = chat.load_ids()
    convs = chat.load_conversations()
    order = only or list(convs)
    out_path = RUNS / f"{model}.jsonl"
    results = []
    for n, conv_id in enumerate(order, 1):
        result = chat.play(convs[conv_id], model=model, verbose=False)
        last = result["turns"][-1]
        print(
            f"  {n:2}/{len(order)} {conv_id}: {last.get('outcome')} -> {last.get('stage')} ({sum(t['seconds'] for t in result['turns']):.0f} s)"
        )
        results.append(result)
    # GHL's opportunity search lags a few seconds behind updates, so read the final
    # state only after every conversation is done.
    time.sleep(30)
    for result in results:
        result["final"] = chat.final_state(ids, result["contact_id"])
    logs = log_rows([t["message_id"] for r in results for t in r["turns"]])
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for r in results:
            for t in r["turns"]:
                t["log"] = logs.get(t["message_id"])
            f.write(json.dumps(r, default=str) + "\n")
    events = calendar_events(ids)
    (RUNS / f"{model}-calendar.json").write_text(
        json.dumps(events, indent=2), encoding="utf-8"
    )
    print(f"  wrote {out_path.relative_to(ROOT)} and {len(events)} calendar events")


def judge(model: str) -> None:
    client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY"))
    system = [
        {
            "type": "text",
            "text": JUDGE_PROMPT.format(kb=kb_text()),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    lines = (RUNS / f"{model}.jsonl").read_text(encoding="utf-8").splitlines()
    out = []
    for r in map(json.loads, lines):
        for i, t in enumerate(r["turns"]):
            reply = t.get("reply")
            if not reply:
                continue
            resp = client.messages.create(
                model=JUDGE_MODEL,
                max_tokens=2000,
                system=system,
                output_config={
                    "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}
                },
                messages=[
                    {
                        "role": "user",
                        "content": f"<customer>{t['body']}</customer>\n<reply>{reply}</reply>",
                    }
                ],
            )
            text = next(b.text for b in resp.content if b.type == "text")
            claims = json.loads(text)["unsupported_claims"]
            out.append(
                {"id": r["id"], "turn": i, "reply": reply, "unsupported_claims": claims}
            )
            if claims:
                print(f"  {r['id']} turn {i}: {claims}")
    path = RUNS / f"{model}-judge.jsonl"
    path.write_text("".join(json.dumps(o) + "\n" for o in out), encoding="utf-8")
    flagged = sum(bool(o["unsupported_claims"]) for o in out)
    print(
        f"  judged {len(out)} replies, {flagged} with unsupported claims -> {path.relative_to(ROOT)}"
    )


def human_sample(model: str, k: int = 10) -> None:
    """Pick 10 judged replies (seed 42) for the hand check in data/human_check.csv."""
    rows = [
        json.loads(x)
        for x in (RUNS / f"{model}-judge.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    picked = random.Random(SEED).sample(rows, k)
    path = ROOT / "data" / "human_check.csv"
    if path.exists():
        print(f"  {path.relative_to(ROOT)} exists, not overwritten")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["model", "id", "turn", "judge_flags", "my_verdict", "note", "reply"]
        )
        for p in picked:
            w.writerow(
                [
                    model,
                    p["id"],
                    p["turn"],
                    len(p["unsupported_claims"]),
                    "",
                    "",
                    p["reply"],
                ]
            )
    print(f"  wrote {k} replies to {path.relative_to(ROOT)} for the hand check")


def main(args: list[str]) -> int:
    only = None
    if "--only" in args:
        only = args[args.index("--only") + 1].split(",")
    try:
        if "--judge" in args:
            judge(args[args.index("--judge") + 1])
            return 0
        models = [args[args.index("--model") + 1]] if "--model" in args else MODELS
        for model in models:
            run(model, only)
            judge(model)
        if not only:
            human_sample(models[0])
    except (
        ConfigError,
        ghl.GHLError,
        httpx.HTTPError,
        psycopg.Error,
        anthropic.APIError,
        FileNotFoundError,
    ) as exc:
        print(f"run_eval FAILED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

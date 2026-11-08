"""Score the eval runs against data/expected.csv and write docs/report.md.

Reads data/runs/<model>.jsonl, <model>-calendar.json, <model>-judge.jsonl and,
when filled in, data/human_check.csv.
"""

import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

# Scripts run as files (python scripts/x.py), so the repo root is not on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ROOT

RUNS = ROOT / "data" / "runs"
FIRST_RUN = ROOT / "data" / "runs-1"
CHANGES = [
    "The help center now states that any question the chat cannot answer, and any request for a person, goes to the office team, who reply within 1 business day. The prompt already promised this, but only billing questions had it in the help center.",
    'The maintenance plan article title says "maintenance plan", so a question with those words finds it.',
    "The ZIP guard now turns every out-of-area conversation into a decline with intent out_of_area, not only the ones where the AI tried to offer times.",
    "The prompt says not to add rules, limits or advice the articles do not state.",
    "The eval reads the final pipeline stage 30 s after the last conversation. In the first run it read it right away, before GHL's opportunity search had caught up, so some stages showed the value from the turn before.",
]
OUT = ROOT / "docs" / "report.md"
MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5"]
AREA = {
    "78701", "78702", "78703", "78704", "78705", "78721", "78722", "78723", "78724",
    "78727", "78728", "78729", "78731", "78741", "78744", "78745", "78746", "78748",
    "78749", "78750", "78751", "78752", "78753", "78756", "78757", "78758", "78759",
    "78664", "78665", "78681", "78660", "78613",
}  # fmt: skip


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def last_log(conv: dict) -> dict:
    for turn in reversed(conv["turns"]):
        if turn.get("log"):
            return turn["log"]
    return {}


def score(model: str, expected: dict[str, dict], runs: Path = RUNS) -> dict:
    convs = {c["id"]: c for c in load_jsonl(runs / f"{model}.jsonl")}
    judged = load_jsonl(runs / f"{model}-judge.jsonl")
    events = json.loads((runs / f"{model}-calendar.json").read_text(encoding="utf-8"))
    m = Counter()
    errors = []
    for cid, exp in expected.items():
        conv = convs[cid]
        log = last_log(conv)
        outcomes = [t.get("outcome") for t in conv["turns"]]
        booked = "booked" in outcomes
        should = exp["should_book"] == "yes"
        handoff = "handoff" in outcomes
        stage = conv["final"]["stage"]
        zip_code = conv["final"]["fields"].get("zip_code")
        checks = {
            "intent": log.get("intent") == exp["intent"],
            "booking": booked == should,
            "stage": stage == exp["final_stage"],
        }
        if exp["tier"]:
            checks["tier"] = log.get("tier") == exp["tier"]
            m["tier_total"] += 1
        for name, ok in checks.items():
            m[name] += ok
        m["handoff_tp"] += handoff and exp["handoff"] == "yes"
        m["handoff_fp"] += handoff and exp["handoff"] == "no"
        m["handoff_fn"] += (not handoff) and exp["handoff"] == "yes"
        m["out_of_area_booked"] += booked and (
            exp["situation"] == "out_of_area" or (zip_code and zip_code not in AREA)
        )
        m["fallback_turns"] += sum(
            bool((t.get("log") or {}).get("used_fallback")) for t in conv["turns"]
        )
        failed = [k for k, ok in checks.items() if not ok]
        if failed:
            errors.append(
                f"{cid} ({exp['situation']}): "
                + "; ".join(
                    {
                        "intent": f"intent {log.get('intent')}, expected {exp['intent']}",
                        "tier": f"tier {log.get('tier')}, expected {exp['tier']}",
                        "booking": f"booked {'yes' if booked else 'no'}, expected {exp['should_book']}",
                        "stage": f"stage {stage}, expected {exp['final_stage']}",
                    }[k]
                    for k in failed
                )
            )
    starts = Counter(e["startTime"] for e in events)
    turns = [t for c in convs.values() for t in c["turns"]]
    latencies = [
        t["log"]["latency_ms"]
        for t in turns
        if t.get("log") and t["log"].get("latency_ms")
    ]
    flagged = [j for j in judged if j["unsupported_claims"]]
    return {
        "model": model,
        "n": len(expected),
        "m": m,
        "errors": errors,
        "duplicate_slots": sum(n - 1 for n in starts.values() if n > 1),
        "events": len(events),
        "replies": len(judged),
        "flagged": flagged,
        "flagged_convs": len({j["id"] for j in flagged}),
        "cost_per_conv": sum((t.get("log") or {}).get("cost_usd", 0) for t in turns)
        / len(expected),
        "median_flow_ms": statistics.median(latencies) if latencies else 0,
        "median_e2e_s": statistics.median(t["seconds"] for t in turns),
        "turns": len(turns),
    }


def pct(a: int, b: int) -> str:
    return f"{a} of {b} ({100 * a / b:.0f}%)" if b else "n/a"


def passes(r: dict) -> dict[str, bool]:
    m = r["m"]
    tp, fn = m["handoff_tp"], m["handoff_fn"]
    return {
        "booking right in 45 of 50 or more": m["booking"] >= 45,
        "0 duplicate slots": r["duplicate_slots"] == 0,
        "0 out-of-area bookings": m["out_of_area_booked"] == 0,
        "handoff recall 90% or more": tp + fn > 0 and tp / (tp + fn) >= 0.9,
        "at most 1 invented claim in 50 conversations": r["flagged_convs"] <= 1,
    }


def human_check() -> list[dict]:
    path = ROOT / "data" / "human_check.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if row["my_verdict"]]


def render(results: list[dict], first: list[dict]) -> str:
    lines = [
        "# Evaluation report",
        "",
        "I ran the 50 synthetic conversations in `data/conversations.jsonl` through the live flow (GHL sandbox, n8n, Claude), once per model, with the demo data reset before each run. The answer key is `data/expected.csv`. Every number below comes from `scripts/report.py` over the files in `data/runs/`.",
        "",
        "## Results",
        "",
        "| Metric | " + " | ".join(r["model"] for r in results) + " |",
        "|---|" + "---|" * len(results),
    ]

    def row(name, fn):
        lines.append(f"| {name} | " + " | ".join(fn(r) for r in results) + " |")

    row(
        "Booking right (booked when it should, not when it should not)",
        lambda r: pct(r["m"]["booking"], r["n"]),
    )
    row("Final pipeline stage right", lambda r: pct(r["m"]["stage"], r["n"]))
    row("Intent right (last turn)", lambda r: pct(r["m"]["intent"], r["n"]))
    row(
        "Tier right (where the rule sets one)",
        lambda r: pct(r["m"]["tier"], r["m"]["tier_total"]),
    )
    row(
        "Duplicate slots in the calendar",
        lambda r: f"{r['duplicate_slots']} ({r['events']} events)",
    )
    row("Out-of-area bookings", lambda r: str(r["m"]["out_of_area_booked"]))
    row(
        "Handoff precision",
        lambda r: pct(
            r["m"]["handoff_tp"], r["m"]["handoff_tp"] + r["m"]["handoff_fp"]
        ),
    )
    row(
        "Handoff recall",
        lambda r: pct(
            r["m"]["handoff_tp"], r["m"]["handoff_tp"] + r["m"]["handoff_fn"]
        ),
    )
    row(
        "Conversations with an invented claim (Claude judge)",
        lambda r: (
            f"{r['flagged_convs']} ({len(r['flagged'])} of {r['replies']} replies)"
        ),
    )
    row(
        "Turns where the fixed rule took over",
        lambda r: f"{r['m']['fallback_turns']} of {r['turns']}",
    )
    row("Cost per conversation", lambda r: f"${r['cost_per_conv']:.4f}")
    row(
        "Median time in the flow per reply",
        lambda r: f"{r['median_flow_ms'] / 1000:.1f} s",
    )
    row("Median time per reply, end to end", lambda r: f"{r['median_e2e_s']:.1f} s")

    lines += ["", "## Acceptance", ""]
    for r in results:
        checks = passes(r)
        lines.append(
            f"{r['model']}: {sum(checks.values())} of {len(checks)} checks pass."
        )
        lines += [
            f"- {'pass' if ok else 'FAIL'}: {name}" for name, ok in checks.items()
        ]
        lines.append("")
    passing = [r for r in results if all(passes(r).values())]
    if passing:
        best = min(passing, key=lambda r: r["cost_per_conv"])
        lines += [
            "## Default model",
            "",
            f"Rule: the cheapest model that passes every acceptance check. That is **{best['model']}** at ${best['cost_per_conv']:.4f} per conversation.",
            "",
        ]
        for r in results:
            failed = [name for name, ok in passes(r).items() if not ok]
            if failed:
                lines += [
                    (
                        f"{r['model']} costs ${r['cost_per_conv']:.4f} per conversation and is faster "
                        f"({r['median_flow_ms'] / 1000:.1f} s per reply), but it failed: {', '.join(failed)}. "
                        "A wrong fact sent to a customer costs more than the difference, so I keep the rule."
                    ),
                    "",
                ]
    lines += ["## Errors", ""]
    for r in results:
        lines.append(f"### {r['model']}")
        lines.append("")
        lines += [f"- {e}" for e in r["errors"]] or ["- none"]
        if r["flagged"]:
            lines += ["", "Replies the judge flagged:", ""]
            for j in r["flagged"]:
                lines.append(
                    f"- {j['id']} turn {j['turn']}: {'; '.join(j['unsupported_claims'])}"
                )
        lines.append("")
    checked = human_check()
    if checked:
        agree = sum(
            row["my_verdict"] == ("flagged" if int(row["judge_flags"]) else "ok")
            for row in checked
        )
        lines += [
            "## Hand check of the judge",
            "",
            f"I read {len(checked)} replies picked at random (seed 42) against the help center. My verdict matched the judge on {agree} of {len(checked)}.",
            "",
            "| Reply | Judge | Me | Note |",
            "|---|---|---|---|",
        ]
        for row in checked:
            judge = "flagged" if int(row["judge_flags"]) else "ok"
            lines.append(
                f"| {row['id']} turn {row['turn']} | {judge} | {row['my_verdict']} | {row['note']} |"
            )
        lines.append("")
    reliability = ROOT / "data" / "reliability.json"
    if reliability.exists():
        tests = json.loads(reliability.read_text(encoding="utf-8"))
        lost = sum(t["lost"] for t in tests)
        dupes = sum(t["duplicate_replies"] for t in tests)
        lines += [
            "## Reliability",
            "",
            f"`scripts/reliability_test.py` breaks one thing at a time on the live flow and puts it back afterwards. Result: {sum(t['pass'] for t in tests)} of {len(tests)} tests pass, {lost} lost messages, {dupes} duplicate replies.",
            "",
            "| Test | Expected | What happened | Pass |",
            "|---|---|---|---|",
        ]
        for t in tests:
            result = t["result"].replace("|", "/").split(" Reply: ")[0]
            lines.append(
                f"| {t['test']} | {t['expected']} | {result} | {'yes' if t['pass'] else 'no'} |"
            )
        lines += [
            "",
            "In the taken-time test, the taken time had already left the open times list when the customer answered, so the guard in `Decide` caught it. The second check right before booking (`Recheck slot`) covers the case where the time is taken in the seconds between those two calls.",
            "",
        ]
    if first:
        lines += [
            "## First run and what I changed",
            "",
            "The first full run found real problems, so I fixed them and ran all 50 conversations again with both models. The first run is kept in `data/runs-1/`.",
            "",
            "| First run | " + " | ".join(r["model"] for r in first) + " |",
            "|---|" + "---|" * len(first),
            "| Booking right | "
            + " | ".join(pct(r["m"]["booking"], r["n"]) for r in first)
            + " |",
            "| Intent right | "
            + " | ".join(pct(r["m"]["intent"], r["n"]) for r in first)
            + " |",
            "| Conversations with an invented claim | "
            + " | ".join(str(r["flagged_convs"]) for r in first)
            + " |",
            "",
            "Changes:",
            "",
        ]
        lines += [f"- {c}" for c in CHANGES]
        lines.append("")
    lines += [
        "## How the numbers are counted",
        "",
        "- Booking right: the conversation reached a booked visit if and only if the answer key says it should.",
        "- Intent and tier: the values the agent recorded on the last turn of the conversation.",
        "- Handoff: any turn that sent the conversation to a person. Recall is over the 6 conversations that should go to a person.",
        "- Invented claims: Claude Sonnet 5.5 reads every reply next to all 25 help center articles and lists business facts the articles do not support. Visit times from the calendar do not count. The judge is the same model as one of the two candidates, so I also checked 10 replies by hand (above).",
        '- The demo calendar only has Monday to Saturday, 8 am to 6 pm. When the first day fills up, an emergency gets the first open time, which can be later than the "today or tomorrow" the help center promises. A real shop would add an on-call calendar for after-hours visits.',
        "- Cost: the token counts from each Claude call at list prices. GHL, n8n and the embedding service add no per-call cost.",
        "- Time in the flow: from the webhook call to the logged turn, measured inside n8n. End to end also counts storing the message in GHL and the network.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    with (ROOT / "data" / "expected.csv").open(encoding="utf-8") as f:
        expected = {row["id"]: row for row in csv.DictReader(f)}
    results = [
        score(m, expected) for m in MODELS if (RUNS / f"{m}-judge.jsonl").exists()
    ]
    if not results:
        print("no runs found in data/runs")
        return 1
    first = [
        score(m, expected, FIRST_RUN)
        for m in MODELS
        if (FIRST_RUN / f"{m}-judge.jsonl").exists()
    ]
    OUT.write_text(render(results, first), encoding="utf-8")
    for r in results:
        print(r["model"], {k: v for k, v in passes(r).items()})
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Set up the Kestrel sub-account and save every id the flow needs to config/ghl_ids.json.

Creates the contact custom fields, the tags and the visit calendar when they are missing.
The pipeline cannot be created with a Private Integration Token, so it is made by hand
(docs/setup-ghl.md) and this script only reads it. Safe to run more than once.
"""

import datetime
import json
import sys
import time
from pathlib import Path

# Scripts run as files (python scripts/x.py), so the repo root is not on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ghl
from config import ROOT, ConfigError, env

IDS_FILE = ROOT / "config" / "ghl_ids.json"

PIPELINE = "Service Leads"
STAGES = ["New Lead", "Qualified", "Booked", "Needs Human", "Lost"]
CALENDAR = "Service Visit"
TZ = "America/Chicago"
# name -> (dataType, options). GHL builds the field key from the name: "AI Score" -> contact.ai_score.
FIELDS = {
    "AI Score": ("NUMERICAL", None),
    "AI Tier": ("SINGLE_OPTIONS", ["hot", "warm", "cold"]),
    "AI Intent": (
        "SINGLE_OPTIONS",
        [
            "question",
            "book_service",
            "install_quote",
            "emergency",
            "out_of_area",
            "billing_or_complaint",
            "job_seeker",
            "spam",
        ],
    ),
    "AI Reason": ("LARGE_TEXT", None),
    "Service Type": ("TEXT", None),
    "Zip Code": ("TEXT", None),
    "Urgency": ("SINGLE_OPTIONS", ["emergency", "this_week", "flexible"]),
}
# ai-test marks every contact the scripts create, so reset_demo.py deletes only those.
TAGS = ["needs-human", "out-of-area", "spam", "job-seeker", "ai-test"]


def field_key(name: str) -> str:
    return "contact." + name.lower().replace(" ", "_")


def setup_fields(loc: str) -> dict:
    path = f"/locations/{loc}/customFields"
    existing = {
        f["fieldKey"]: f
        for f in ghl.request("GET", path, params={"model": "contact"})["customFields"]
    }
    ids = {}
    for name, (data_type, options) in FIELDS.items():
        key = field_key(name)
        if key not in existing:
            body = {"name": name, "dataType": data_type, "model": "contact"}
            if options:
                body["options"] = options
            existing[key] = ghl.request("POST", path, json=body)["customField"]
            print(f"created field {key}")
        field = existing[key]
        if options and sorted(field.get("picklistOptions") or []) != sorted(options):
            raise RuntimeError(
                f"field {key} has options {field.get('picklistOptions')}"
            )
        ids[key.removeprefix("contact.")] = field["id"]
    return ids


def setup_tags(loc: str) -> dict:
    path = f"/locations/{loc}/tags"
    existing = {t["name"]: t["id"] for t in ghl.request("GET", path)["tags"]}
    for name in TAGS:
        if name not in existing:
            existing[name] = ghl.request("POST", path, json={"name": name})["tag"]["id"]
            print(f"created tag {name}")
    return {name: existing[name] for name in TAGS}


def find_pipeline(loc: str) -> dict:
    pipelines = ghl.request(
        "GET", "/opportunities/pipelines", params={"locationId": loc}
    )["pipelines"]
    match = [p for p in pipelines if p["name"] == PIPELINE]
    if not match:
        raise RuntimeError(
            f"pipeline {PIPELINE!r} not found. Create it by hand (docs/setup-ghl.md)."
        )
    stages = {s["name"]: s["id"] for s in match[0]["stages"]}
    missing = [s for s in STAGES if s not in stages]
    if missing:
        raise RuntimeError(f"pipeline {PIPELINE!r} is missing stages {missing}")
    return {"id": match[0]["id"], "stages": {s: stages[s] for s in STAGES}}


def setup_calendar(loc: str) -> str:
    calendars = ghl.request("GET", "/calendars/", params={"locationId": loc})[
        "calendars"
    ]
    match = [c for c in calendars if c["name"] == CALENDAR]
    if match:
        return match[0]["id"]
    body = {
        "locationId": loc,
        "name": CALENDAR,
        "description": "2-hour arrival window for a repair, tune-up or install estimate.",
        # An event calendar uses only these open hours. A round robin calendar also applies the
        # user's own working hours (Monday to Friday by default) and drops Saturday.
        "calendarType": "event",
        # Monday to Saturday, 8 am to 6 pm in the sub-account time zone.
        "openHours": [
            {
                "daysOfTheWeek": [day],
                "hours": [
                    {"openHour": 8, "openMinute": 0, "closeHour": 18, "closeMinute": 0}
                ],
            }
            for day in range(1, 7)
        ],
        # In minutes: with "hours" as the unit, GHL stored 2 hours as 0.03 hours.
        "slotDuration": 120,
        "slotDurationUnit": "mins",
        "slotInterval": 120,
        "slotIntervalUnit": "mins",
        "autoConfirm": True,
    }
    calendar = ghl.request("POST", "/calendars/", json=body)["calendar"]
    print(f"created calendar {CALENDAR}")
    return calendar["id"]


def verify(loc: str, ids: dict) -> None:
    """Read every saved id back from GHL."""
    fields = {
        f["id"]
        for f in ghl.request(
            "GET", f"/locations/{loc}/customFields", params={"model": "contact"}
        )["customFields"]
    }
    assert set(ids["fields"].values()) <= fields, "a field id is missing"
    tags = {t["id"] for t in ghl.request("GET", f"/locations/{loc}/tags")["tags"]}
    assert set(ids["tags"].values()) <= tags, "a tag id is missing"
    cal = ghl.request("GET", f"/calendars/{ids['calendar_id']}")["calendar"]
    assert cal["id"] == ids["calendar_id"]
    assert (cal["slotDuration"], cal["slotDurationUnit"]) == (120, "mins"), (
        "slot length"
    )
    # Next 8 days must offer 5 slots per open day (8, 10, 12, 14, 16) and include a Saturday.
    now = int(time.time() * 1000)
    slots = ghl.request(
        "GET",
        f"/calendars/{cal['id']}/free-slots",
        params={"startDate": now, "endDate": now + 8 * 86_400_000, "timezone": TZ},
    )
    days = {d: v["slots"] for d, v in slots.items() if isinstance(v, dict)}
    weekdays = {datetime.date.fromisoformat(d).weekday() for d in days}
    assert 5 in weekdays and 6 not in weekdays, f"open days are wrong: {sorted(days)}"
    starts = {s[11:16] for v in days.values() for s in v}
    assert starts <= {"08:00", "10:00", "12:00", "14:00", "16:00"}, f"slots {starts}"
    ghl.request("GET", f"/users/{ids['user_id']}")
    assert find_pipeline(loc) == ids["pipeline"]


def main() -> int:
    try:
        loc = env("GHL_LOCATION_ID")
        users = ghl.request("GET", "/users/", params={"locationId": loc})["users"]
        if not users:
            raise RuntimeError("the sub-account has no users")
        user_id = users[0]["id"]
        ids = {
            "location_id": loc,
            "user_id": user_id,
            "fields": setup_fields(loc),
            "tags": setup_tags(loc),
            "calendar_id": setup_calendar(loc),
            "pipeline": find_pipeline(loc),
        }
        verify(loc, ids)
    except (ConfigError, RuntimeError, ghl.GHLError, AssertionError) as exc:
        print(f"setup FAILED: {exc}")
        return 1
    IDS_FILE.parent.mkdir(exist_ok=True)
    IDS_FILE.write_text(json.dumps(ids, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(ids, indent=2))
    print(f"all ids checked against GHL and saved to {IDS_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

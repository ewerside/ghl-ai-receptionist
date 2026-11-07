"""Delete the test data: every GHL contact tagged ai-test, with its appointments and
opportunities, and their rows in the bookings table. Real contacts are never touched.

python scripts/reset_demo.py          delete
python scripts/reset_demo.py --dry    only count
"""

import json
import sys
from pathlib import Path

import psycopg

# Scripts run as files (python scripts/x.py), so the repo root is not on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ghl
from config import CONFIG_DIR, ConfigError, env

TEST_TAG = "ai-test"


def test_contacts(location_id: str) -> list[dict]:
    found, page = [], 1
    while True:
        body = {
            "locationId": location_id,
            "page": page,
            "pageLimit": 100,
            "filters": [{"field": "tags", "operator": "contains", "value": TEST_TAG}],
        }
        batch = ghl.request("POST", "/contacts/search", json=body)["contacts"]
        found += batch
        if len(batch) < 100:
            return found
        page += 1


def main(args: list[str]) -> int:
    dry = "--dry" in args
    try:
        ids = json.loads((CONFIG_DIR / "ghl_ids.json").read_text(encoding="utf-8"))
        contacts = test_contacts(ids["location_id"])
        events = opps = 0
        for contact in contacts:
            # Double check the tag before deleting anything.
            if TEST_TAG not in contact.get("tags", []):
                continue
            cid = contact["id"]
            try:
                appointments = ghl.request("GET", f"/contacts/{cid}/appointments")
            except ghl.GHLError as exc:
                # Search lags a few seconds behind deletes; a gone contact is fine.
                if exc.status in (400, 404) and "not found" in str(exc).lower():
                    continue
                raise
            for event in appointments["events"]:
                events += 1
                if not dry:
                    ghl.request("DELETE", f"/calendars/events/{event['id']}")
            found = ghl.request(
                "GET",
                "/opportunities/search",
                params={"location_id": ids["location_id"], "contact_id": cid},
            )["opportunities"]
            for opp in found:
                opps += 1
                if not dry:
                    ghl.request("DELETE", f"/opportunities/{opp['id']}")
            if not dry:
                ghl.request("DELETE", f"/contacts/{cid}")
        rows = 0
        if not dry and contacts:
            with psycopg.connect(env("DATABASE_URL"), connect_timeout=15) as conn:
                rows = conn.execute(
                    "delete from bookings where contact_id = any(%s)",
                    ([c["id"] for c in contacts],),
                ).rowcount
    except (ConfigError, ghl.GHLError, psycopg.Error, FileNotFoundError) as exc:
        print(f"reset FAILED: {exc}")
        return 1
    verb = "would delete" if dry else "deleted"
    print(
        f"{verb} {len(contacts)} test contacts, {events} appointments, "
        f"{opps} opportunities, {rows} booking rows"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

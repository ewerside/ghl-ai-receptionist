"""Send failed events again: each payload in failed_events goes back to the n8n webhook.

The error workflow stores the original webhook payload and marks the message as failed,
so the flow claims it again and finishes it. A replayed event gets replayed_at.

python scripts/replay_failed.py          replay everything not replayed yet
python scripts/replay_failed.py --dry    only list
"""

import sys
from pathlib import Path

import httpx
import psycopg

# Scripts run as files (python scripts/x.py), so the repo root is not on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ConfigError, env, n8n_base_url


def main(args: list[str]) -> int:
    dry = "--dry" in args
    done = failed = 0
    try:
        url = f"{n8n_base_url()}/webhook/ghl-inbound"
        headers = {"X-Inbound-Token": env("INBOUND_TOKEN")}
        with psycopg.connect(env("DATABASE_URL"), connect_timeout=15) as conn:
            rows = conn.execute(
                "select id, step, payload from failed_events "
                "where replayed_at is null and payload ? 'message_id' order by id"
            ).fetchall()
            print(f"{len(rows)} failed events to replay")
            for event_id, step, payload in rows:
                print(
                    f"  #{event_id} failed at {step}: message {payload['message_id']}",
                    end="",
                )
                if dry:
                    print()
                    continue
                resp = httpx.post(url, json=payload, headers=headers, timeout=120)
                # A failed run answers 200 with an empty body, so check before parsing.
                ok = resp.status_code == 200 and resp.content
                answer = resp.json() if ok else {}
                # "duplicate" means an earlier replay already finished this message.
                if answer.get("status") in ("done", "duplicate"):
                    conn.execute(
                        "update failed_events set replayed_at = now() where id = %s",
                        (event_id,),
                    )
                    conn.commit()
                    done += 1
                    print(f" -> {answer['status']}")
                else:
                    failed += 1
                    print(f" -> still failing (HTTP {resp.status_code})")
    except (ConfigError, psycopg.Error, httpx.HTTPError) as exc:
        print(f"replay FAILED: {exc}")
        return 1
    if not dry:
        print(f"replayed {done}, still failing {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Write 50 synthetic test conversations and their answer key.

Output: data/conversations.jsonl (what the customer says) and data/expected.csv (what the agent
should do). Every conversation follows one row of the business rule table in README.md.
The script checks its own output: every fact in the key exists in kb/, and each of the 8
situations has at least 4 conversations.
"""

import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

import yaml

# Make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ROOT

SEED = 42
DATA = ROOT / "data"
MIN_PER_SITUATION = 4

IN_AREA = ["78701", "78702", "78704", "78723", "78745", "78748", "78757", "78759",
           "78664", "78681", "78660", "78613"]  # fmt: skip
OUT_OF_AREA = ["78626", "78666", "78205", "78640", "78610", "76574"]
FIRST = ["Avery", "Blake", "Carmen", "Dmitri", "Elena", "Felix", "Grace", "Hector",
         "Imani", "Jonah", "Keiko", "Luis", "Maya", "Nolan", "Opal", "Priya", "Quinn",
         "Rosa", "Silas", "Tara", "Uma", "Victor", "Wendy", "Xavier", "Yara", "Zane"]  # fmt: skip
LAST = ["Abbott", "Bishop", "Castillo", "Dalton", "Ellis", "Fowler", "Garza", "Hollis",
        "Ingram", "Jensen", "Kemp", "Lowell", "Medina", "Nash", "Ortega", "Pruitt",
        "Quintero", "Ramsey", "Sutton", "Tran", "Vance", "Whitfield"]  # fmt: skip

ACCEPT = [
    "The first time works for me, please book it.",
    "Book the earliest one please.",
    "Yes, the first slot is good.",
]

# Each situation: the expected values from the business rules, and message templates.
# A template is (messages, should_book, facts). {zip} is filled in per conversation.
# When should_book is true, the last message accepts an offered time.
SITUATIONS = {
    "emergency": {
        "count": 7,
        "intent": "emergency",
        "tier": "hot",
        "handoff": "no",
        "templates": [
            (
                [
                    "My AC stopped working and it's 98 degrees",
                    "I'm in {zip} and I own the house.",
                    "{accept}",
                ],
                True,
                ["emergency"],
            ),
            (
                [
                    "Water is pouring from a pipe under my kitchen sink right now!",
                    "ZIP {zip}, it's my house.",
                    "{accept}",
                ],
                True,
                ["emergency", "emergency_safety"],
            ),
            (
                [
                    "Sewage is coming up in my bathtub. Can someone come today?",
                    "{zip}. Yes I'm the homeowner.",
                    "{accept}",
                ],
                True,
                ["emergency"],
            ),
            (
                [
                    "No AC at all and it's over 100 outside, my kids are melting. Homeowner in {zip}.",
                    "{accept}",
                ],
                True,
                ["emergency"],
            ),
            (
                [
                    "Our heat died and it's 30 degrees tonight. We own the home, zip {zip}.",
                    "{accept}",
                ],
                True,
                ["emergency"],
            ),
            (
                [
                    "Help, my water heater is leaking all over the garage floor. I own the place, {zip}."
                ],
                False,
                ["emergency", "emergency_safety"],
            ),
            (
                [
                    "AC is blowing hot air and it's 96 degrees in here. I'm in {zip}, own the house."
                ],
                False,
                ["emergency"],
            ),
        ],
    },
    "install_owner": {
        "count": 6,
        "intent": "install_quote",
        "tier": "hot",
        "handoff": "no",
        "templates": [
            (
                [
                    "Hi, my AC is 18 years old and I want a quote for a new system.",
                    "I own the house, ZIP {zip}.",
                    "{accept}",
                ],
                True,
                ["install_estimate"],
            ),
            (
                [
                    "How much would a new heat pump cost? Thinking of replacing my old furnace and AC.",
                    "I'm the owner, {zip}.",
                    "{accept}",
                ],
                True,
                ["install_estimate", "install_prices"],
            ),
            (
                [
                    "We just bought a house in {zip} and want to replace the whole HVAC system. Can you give us an estimate?",
                    "{accept}",
                ],
                True,
                ["install_estimate"],
            ),
            (
                [
                    "I'd like an estimate for a new tankless water heater. Homeowner, {zip}.",
                    "{accept}",
                ],
                True,
                ["install_estimate"],
            ),
            (
                [
                    "Looking to replace my central AC before summer. I own my home in {zip}. What does the estimate cost?"
                ],
                False,
                ["install_estimate"],
            ),
            (
                ["Can you quote a new furnace? I own the house.", "Zip is {zip}."],
                False,
                ["install_estimate"],
            ),
        ],
    },
    "repair": {
        "count": 7,
        "intent": "book_service",
        "tier": "warm",
        "handoff": "no",
        "templates": [
            (
                [
                    "My AC is making a loud buzzing noise but still cooling a bit.",
                    "{zip}, I own the home.",
                    "{accept}",
                ],
                True,
                ["trip_fee"],
            ),
            (
                [
                    "I'd like to schedule an AC tune-up before summer.",
                    "I'm in {zip}, homeowner.",
                    "{accept}",
                ],
                True,
                ["tune_up"],
            ),
            (
                [
                    "My kitchen drain is really slow. Can you send someone?",
                    "{zip}. I own it.",
                    "{accept}",
                ],
                True,
                ["drains"],
            ),
            (
                [
                    "The water heater only gives lukewarm water. Homeowner in {zip}.",
                    "{accept}",
                ],
                True,
                ["water_heater", "trip_fee"],
            ),
            (
                [
                    "I rent in {zip} and the AC keeps turning off by itself. Can I book a repair?",
                    "{accept}",
                ],
                True,
                ["trip_fee"],
            ),
            (
                [
                    "Furnace makes a clicking sound when it starts. I own my house in {zip}. What would a visit cost?"
                ],
                False,
                ["trip_fee"],
            ),
            (
                ["Need a heating tune-up for fall.", "{zip}, I'm the owner."],
                False,
                ["tune_up"],
            ),
        ],
    },
    "tenant_install": {
        "count": 5,
        "intent": "install_quote",
        "tier": "warm",
        "handoff": "no",
        "templates": [
            (
                [
                    "I rent my apartment and the AC is really old. Can you install a new one?",
                    "{zip}.",
                ],
                False,
                ["owner_rule"],
            ),
            (
                [
                    "I'm a tenant in {zip}. I want a quote for a new heat pump.",
                    "No, I don't own it. Can't I just book the estimate myself?",
                ],
                False,
                ["owner_rule"],
            ),
            (
                [
                    "Hi, I'm renting a house in {zip} and want a new water heater installed. Can you come give a quote?"
                ],
                False,
                ["owner_rule"],
            ),
            (
                [
                    "Can I get an estimate for a new HVAC system? I'm renting.",
                    "ZIP is {zip}.",
                ],
                False,
                ["owner_rule"],
            ),
            (
                [
                    "My landlord said I can look for quotes for a new AC. I'm a renter in {zip}."
                ],
                False,
                ["owner_rule"],
            ),
        ],
    },
    "out_of_area": {
        "count": 6,
        "intent": "out_of_area",
        "tier": "cold",
        "handoff": "no",
        "templates": [
            (
                [
                    "My AC isn't cooling. Can you come out?",
                    "I'm in {out_zip}, I own the house.",
                ],
                False,
                ["service_area"],
            ),
            (
                ["Do you service {out_zip}? Need a water heater repair."],
                False,
                ["service_area"],
            ),
            (
                ["I need a quote for a new furnace. Homeowner, zip {out_zip}."],
                False,
                ["service_area"],
            ),
            (
                ["Drain clogged, can you send someone today?", "{out_zip}"],
                False,
                ["service_area"],
            ),
            (
                ["Hi, looking for an AC tune-up. I live in {out_zip}."],
                False,
                ["service_area"],
            ),
            (
                [
                    "Leaking pipe in my laundry room, homeowner in {out_zip}.",
                    "Is there any way you can come anyway?",
                ],
                False,
                ["service_area"],
            ),
        ],
    },
    "handoff": {
        "count": 6,
        "intent": "billing_or_complaint",
        "tier": "",
        "handoff": "yes",
        "templates": [
            (
                ["I was charged twice for last week's repair. I want a refund."],
                False,
                ["billing_help"],
            ),
            (
                [
                    "Your technician left mud all over my carpet and the AC still isn't fixed. I'm really unhappy."
                ],
                False,
                ["billing_help"],
            ),
            (["Can I talk to a real person please?"], False, ["billing_help"]),
            (
                ["My invoice says $450 but I was quoted less. Who can fix this?"],
                False,
                ["billing_help"],
            ),
            (
                [
                    "I want to file a complaint about yesterday's visit.",
                    "The tech was two hours late and didn't call.",
                ],
                False,
                ["billing_help"],
            ),
            (
                ["Stop with the bot, I need to speak with a manager about my bill."],
                False,
                ["billing_help"],
            ),
        ],
    },
    "job_or_spam": {
        "count": 6,
        "templates": [
            (
                ["Hi, are you hiring HVAC techs? I have 5 years of experience."],
                False,
                ["careers"],
                "job_seeker",
            ),
            (
                ["I'm a licensed plumber looking for work. Can I send my resume here?"],
                False,
                ["careers"],
                "job_seeker",
            ),
            (
                ["Do you have any openings for apprentices?"],
                False,
                ["careers"],
                "job_seeker",
            ),
            (
                [
                    "We help contractors get 10x more leads with SEO. Reply YES for a free audit."
                ],
                False,
                [],
                "spam",
            ),
            (
                ["Congratulations! You won a gift card, click the link to claim it."],
                False,
                [],
                "spam",
            ),
            (
                ["Buy cheap followers for your business page, best prices guaranteed."],
                False,
                [],
                "spam",
            ),
        ],
        "tier": "cold",
        "handoff": "no",
    },
    "question": {
        "count": 7,
        "intent": "question",
        "tier": "",
        "handoff": "no",
        "templates": [
            (
                ["How much do you charge just to come out and look at my AC?"],
                False,
                ["trip_fee"],
            ),
            (["What warranty do you give on repairs?"], False, ["warranty"]),
            (["Are you open on Sundays?"], False, ["hours"]),
            (["Do you offer financing for a new system?"], False, ["financing"]),
            (["How much is a tune-up?"], False, ["tune_up"]),
            (["What's included in your maintenance plan?"], False, ["care_plan"]),
            (
                ["Is there an extra charge for coming out at night?"],
                False,
                ["emergency"],
            ),
        ],
    },
}


def final_stage(situation: str, should_book: bool) -> str:
    if should_book:
        return "Booked"
    return {
        "emergency": "Qualified",
        "install_owner": "Qualified",
        "repair": "Qualified",
        "tenant_install": "Qualified",
        "out_of_area": "Lost",
        "handoff": "Needs Human",
        "job_or_spam": "Lost",
        "question": "New Lead",
    }[situation]


def build(rng: random.Random) -> tuple[list[dict], list[dict]]:
    conversations, expected = [], []
    names = rng.sample([(f, la) for f in FIRST for la in LAST], 50)
    n = 0
    for situation, spec in SITUATIONS.items():
        templates = spec["templates"]
        assert len(templates) == spec["count"], situation
        for template in templates:
            messages, should_book, facts = template[:3]
            intent = template[3] if len(template) > 3 else spec["intent"]
            first, last = names[n]
            fill = {
                "zip": rng.choice(IN_AREA),
                "out_zip": rng.choice(OUT_OF_AREA),
                "accept": rng.choice(ACCEPT),
            }
            conv_id = f"c{n + 1:02d}"
            conversations.append(
                {
                    "id": conv_id,
                    "contact": {
                        "firstName": first,
                        "lastName": last,
                        "email": f"{first}.{last}@mail.example.com".lower(),
                        # Every phone is in the reserved 555-0100 to 555-0199 range.
                        "phone": f"+1512555{100 + n:04d}",
                    },
                    "messages": [m.format(**fill) for m in messages],
                }
            )
            expected.append(
                {
                    "id": conv_id,
                    "situation": situation,
                    "intent": intent,
                    "tier": spec["tier"],
                    "should_book": "yes" if should_book else "no",
                    "final_stage": final_stage(situation, should_book),
                    "handoff": spec["handoff"],
                    "facts": ";".join(facts),
                }
            )
            n += 1
    # Shuffle so the eval does not run all cases of one situation in a row.
    order = list(range(len(conversations)))
    rng.shuffle(order)
    return [conversations[i] for i in order], [expected[i] for i in order]


def check(conversations: list[dict], expected: list[dict]) -> list[str]:
    errors = []
    fact_ids = {
        f["id"]
        for f in yaml.safe_load(
            (ROOT / "kb" / "facts.yaml").read_text(encoding="utf-8")
        )
    }
    if len(conversations) != 50:
        errors.append(f"{len(conversations)} conversations, expected 50")
    for row in expected:
        for fact in filter(None, row["facts"].split(";")):
            if fact not in fact_ids:
                errors.append(f"{row['id']}: fact {fact!r} is not in kb/facts.yaml")
    for conv in conversations:
        if not 1 <= len(conv["messages"]) <= 4:
            errors.append(f"{conv['id']}: {len(conv['messages'])} messages")
    counts = Counter(row["situation"] for row in expected)
    for situation in SITUATIONS:
        if counts[situation] < MIN_PER_SITUATION:
            errors.append(f"{situation}: only {counts[situation]} conversations")
    print("conversations per situation:")
    for situation in SITUATIONS:
        booked = sum(
            r["should_book"] == "yes" for r in expected if r["situation"] == situation
        )
        print(f"  {situation:<15} {counts[situation]}  (should book: {booked})")
    return errors


def main() -> int:
    conversations, expected = build(random.Random(SEED))
    errors = check(conversations, expected)
    for error in errors:
        print(f"FAIL {error}")
    if errors:
        return 1
    DATA.mkdir(exist_ok=True)
    with (DATA / "conversations.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for conv in conversations:
            f.write(json.dumps(conv) + "\n")
    with (DATA / "expected.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(expected[0]))
        writer.writeheader()
        writer.writerows(expected)
    total_msgs = sum(len(c["messages"]) for c in conversations)
    print(
        f"wrote {len(conversations)} conversations ({total_msgs} customer messages) "
        "and data/expected.csv; every fact found in kb/"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

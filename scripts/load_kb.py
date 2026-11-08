"""Check the FAQ against kb/facts.yaml, then embed it and load it into Postgres.

python scripts/load_kb.py           check, create the tables, load the chunks
python scripts/load_kb.py --check   check only, no database
"""

import re
import sys
from pathlib import Path

import psycopg
import yaml

# Make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ROOT, ConfigError, env

KB_DIR = ROOT / "kb"
SCHEMA_SQL = ROOT / "sql" / "schema.sql"
EXPECTED_ARTICLES = 25
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
MONEY = re.compile(r"\$\d+(?:,\d{3})*")

UPSERT = """
insert into kb_chunks (id, article_id, title, content, embedding)
values (%s, %s, %s, %s, %s::vector)
on conflict (id) do update set
    article_id = excluded.article_id,
    title = excluded.title,
    content = excluded.content,
    embedding = excluded.embedding
"""


def load_facts() -> list[dict]:
    return yaml.safe_load((KB_DIR / "facts.yaml").read_text(encoding="utf-8"))


def load_articles() -> list[dict]:
    """Return each article as {id, title, topic, body}."""
    articles = []
    for path in sorted((KB_DIR / "articles").glob("*.md")):
        _, front, body = path.read_text(encoding="utf-8").split("---\n", 2)
        meta = yaml.safe_load(front)
        articles.append({**meta, "file": path.name, "body": body.strip()})
    return articles


def check_kb(facts: list[dict], articles: list[dict]) -> list[str]:
    errors = []
    if len(articles) != EXPECTED_ARTICLES:
        errors.append(f"{len(articles)} articles, expected {EXPECTED_ARTICLES}")
    fact_text = " ".join(f["text"] for f in facts)
    allowed_money = set(MONEY.findall(fact_text))
    all_text = "\n".join(a["body"] for a in articles)
    for a in articles:
        if a.get("id") != a["file"].removesuffix(".md"):
            errors.append(f"{a['file']}: id does not match the file name")
        if not a.get("title") or not a.get("topic"):
            errors.append(f"{a['file']}: missing title or topic")
        text = a["title"] + "\n" + a["body"]
        for amount in set(MONEY.findall(text)) - allowed_money:
            errors.append(f"{a['file']}: {amount} is not in facts.yaml")
    for fact in facts:
        if not fact["values"]:
            errors.append(f"fact {fact['id']}: no values")
        for value in fact["values"]:
            if value not in fact["text"]:
                errors.append(f"fact {fact['id']}: {value!r} is not in its own text")
            if value not in all_text:
                errors.append(f"fact {fact['id']}: {value!r} is in no article")
    return errors


def embed(texts: list[str]) -> list[str]:
    # Imported here so --check runs without loading the model.
    from fastembed import TextEmbedding

    model = TextEmbedding(
        model_name=EMBED_MODEL, cache_dir=str(ROOT / ".fastembed_cache")
    )
    return [
        "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
        for vec in model.passage_embed(texts)
    ]


def load(articles: list[dict]) -> None:
    # One chunk per article: the articles are short, and a whole article keeps its context.
    rows = [(f"{a['id']}#0", a["id"], a["title"], a["body"]) for a in articles]
    # The title goes into the embedded text so a section still knows its topic.
    vectors = embed([f"{title}\n{body}" for _, _, title, body in rows])
    with psycopg.connect(env("DATABASE_URL"), connect_timeout=15) as conn:
        conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        with conn.cursor() as cur:
            cur.executemany(UPSERT, [(*r, v) for r, v in zip(rows, vectors)])
        stale = conn.execute(
            "delete from kb_chunks where not (id = any(%s))", ([r[0] for r in rows],)
        ).rowcount
        (total,) = conn.execute("select count(*) from kb_chunks").fetchone()
        schema = conn.execute("select current_schema()").fetchone()[0]
    print(f"schema {schema}: {total} rows in kb_chunks, {stale} stale rows removed")


def main(args: list[str]) -> int:
    facts, articles = load_facts(), load_articles()
    errors = check_kb(facts, articles)
    for error in errors:
        print(f"FAIL {error}")
    if errors:
        return 1
    print(f"kb ok: {len(articles)} articles, {len(facts)} facts, every value found")
    if "--check" in args:
        return 0
    try:
        load(articles)
    except (ConfigError, psycopg.Error) as exc:
        print(f"load FAILED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

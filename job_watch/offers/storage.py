"""offers table: offers from every source (RSS, career sites), filtered and scored by V1.

Primary key (company, key): the offer key of the career-site extraction (unique within one
company), "url:<link>" for RSS offers. A database created before career sites (primary key
link) is migrated in place, without losing any offer.
"""
import json
import sqlite3
from collections.abc import Callable

from job_watch import config

# Facts of an offer stored with it, so that rules and scores can be computed again without any LLM call
# (scripts/rescore.py). JSON columns hold lists.
FACT_COLUMNS = {
    "domain": "TEXT", "category": "TEXT", "secondary_category": "TEXT",         # triage
    "detail_summary": "TEXT", "requirements": "TEXT", "city": "TEXT", "country": "TEXT",   # detail fact sheet
    "seniority": "TEXT", "experience_years": "INTEGER", "experience_requirement": "TEXT", "languages": "TEXT",
    "contract": "TEXT", "workload": "TEXT", "salary": "TEXT", "education": "TEXT", "ad_language": "TEXT",
}
JSON_COLUMNS = {"requirements", "languages", "reasons"}
COLUMNS = ("company", "key", "link", "title", "location", "description", "source", "published", "fetched",
           "score", "reasons", "status", *FACT_COLUMNS)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS offers (
    company     TEXT NOT NULL,
    key         TEXT NOT NULL,
    link        TEXT,
    title       TEXT NOT NULL,
    location    TEXT,
    description TEXT,              -- raw text of the ad (RSS description, or career-site page text)
    source      TEXT,              -- RSS source name, or "career_site"
    published   TEXT,
    fetched     TEXT,
    score       INTEGER,
    reasons     TEXT,              -- JSON list: bonuses with their points, or the dealbreakers that rejected it
    status      TEXT,              -- "new" (kept) or "rejected", recomputed by scripts/rescore.py
    {", ".join(f"{name} {kind}" for name, kind in FACT_COLUMNS.items())},
    PRIMARY KEY (company, key)
)
"""

V1_COLUMNS = ("link", "title", "company", "location", "description", "source", "published", "fetched",
              "score", "reasons", "status")


def rss_key(link: str) -> str:
    return f"url:{link}"


def _migrate_from_link_key(conn: sqlite3.Connection) -> None:
    """Move a V1 table (primary key link) to the (company, key) schema, keeping every row."""
    with conn:
        conn.execute("ALTER TABLE offers RENAME TO offers_v1")
        conn.execute(SCHEMA)
        conn.execute(
            f"""INSERT INTO offers (key, company, {', '.join(c for c in V1_COLUMNS if c != 'company')})
                SELECT 'url:' || link, COALESCE(company, 'unknown'),
                       {', '.join(c for c in V1_COLUMNS if c != 'company')}
                FROM offers_v1""")
        conn.execute("DROP TABLE offers_v1")


def connect() -> sqlite3.Connection:
    """Open the database (config.DB_PATH), create the table, or migrate a V1 table."""
    conn = sqlite3.connect(config.DB_PATH)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}
    if columns and "key" not in columns:
        _migrate_from_link_key(conn)
    conn.execute(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}
    for name, kind in FACT_COLUMNS.items():         # table created before the fact sheet: add the columns
        if name not in columns:
            conn.execute(f"ALTER TABLE offers ADD COLUMN {name} {kind}")
    conn.commit()
    return conn


def _row(offer: dict) -> tuple:
    def value(name):
        found = offer.get(name)
        if name in JSON_COLUMNS:
            return json.dumps(found or [], ensure_ascii=False)
        return found if found is not None or name in ("score", "experience_years") else ""
    return tuple(value(name) if name != "status" else offer.get("status", "new") for name in COLUMNS)


def row_to_offer(row: sqlite3.Row) -> dict:
    """A stored offer as a dict, JSON columns decoded (for scripts/rescore.py)."""
    offer = dict(row)
    for name in JSON_COLUMNS:
        if name in offer:
            offer[name] = json.loads(offer[name] or "[]")
    return offer


def known_offers() -> set[tuple[str, str]]:
    """(company, key) of the stored offers."""
    conn = connect()
    try:
        return {(row[0], row[1]) for row in conn.execute("SELECT company, key FROM offers")}
    finally:
        conn.close()


def save_offers(offers: list[dict],
                before_commit: Callable[[sqlite3.Connection], None] | None = None) -> list[tuple[str, str]]:
    """Insert offers not already in the database. Return the (company, key) of the new offers.

    before_commit: optional, writes more rows on the same connection (listed_offers), committed
    together with the offers; if anything fails, nothing is written.
    """
    conn = connect()
    try:
        existing = {(row[0], row[1]) for row in conn.execute("SELECT company, key FROM offers")}
        new_offers, seen = [], set()
        for offer in offers:
            pk = (offer["company"], offer["key"])
            if pk not in existing and pk not in seen:
                new_offers.append(offer)
                seen.add(pk)
        conn.executemany(
            f"INSERT OR IGNORE INTO offers ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
            [_row(o) for o in new_offers],
        )
        if before_commit:
            before_commit(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return [(o["company"], o["key"]) for o in new_offers]

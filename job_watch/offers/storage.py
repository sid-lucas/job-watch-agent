"""offers table: offers from every source (RSS, career sites), filtered and scored by V1.

Primary key (company, key): the offer key of the career-site extraction (unique within one
company), "url:<link>" for RSS offers. A database created before career sites (primary key
link) is migrated in place, without losing any offer.
"""
import json
import sqlite3
from collections.abc import Callable

from job_watch import config

COLUMNS = (
    "company", "key", "link", "title", "location", "description", "source", "published", "fetched",
    "score", "reasons", "status",
    # career-site detail phase (empty for RSS offers and for career-site offers without detail)
    "detail_summary", "requirements", "contract", "workload", "ad_language", "required_languages",
)

SCHEMA = """
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
    reasons     TEXT,
    status      TEXT,
    detail_summary      TEXT,      -- written by the LLM: data to read, never a checked fact
    requirements        TEXT,      -- JSON list, each one quoted from the page
    contract            TEXT,
    workload            TEXT,
    ad_language         TEXT,
    required_languages  TEXT,      -- JSON list
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
    return conn


def _row(offer: dict) -> tuple:
    return (
        offer["company"], offer["key"], offer.get("link", ""), offer["title"], offer.get("location", ""),
        offer.get("description", ""), offer.get("source", ""), offer.get("published", ""),
        offer.get("fetched", ""), offer.get("score"), json.dumps(offer.get("reasons", [])),
        offer.get("status", "new"), offer.get("detail_summary", ""),
        json.dumps(offer.get("requirements", []), ensure_ascii=False), offer.get("contract", ""),
        offer.get("workload", ""), offer.get("ad_language", ""),
        json.dumps(offer.get("required_languages", [])),
    )


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

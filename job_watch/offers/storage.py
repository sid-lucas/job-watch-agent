"""offers table: offers from every source (RSS, career sites), filtered and scored by V1.

Primary key (company, key): the offer key of the career-site extraction (unique within one
company), "url:<link>" for RSS offers. A database created before career sites (primary key
link) is migrated in place, without losing any offer.
"""
import json
import sqlite3
from collections.abc import Callable

from job_watch import config

# Triage and raw criteria answers stored with an offer, so that the score can be computed again
# without any LLM call (scripts/rescore.py). Raw requirements of the ad (matching, brick 1), stored
# so that they are never extracted twice. JSON columns hold lists (criteria_answers: null when every
# model failed; ad_requirements: null when not extracted; the former fact-sheet column "requirements"
# is another one, dropped).
FACT_COLUMNS = {
    "domain": "TEXT",                                                           # triage
    "criteria_questions": "TEXT", "criteria_answers": "TEXT", "criteria_model": "TEXT", "full_ad": "INTEGER",
    "ad_requirements": "TEXT", "ad_requirements_model": "TEXT", "ad_requirements_prompt": "TEXT",
}
JSON_COLUMNS = {"reasons", "criteria_answers", "ad_requirements"}
NULLABLE_JSON = {"criteria_answers", "ad_requirements"}
# Columns of the detail fact sheet, replaced by the criteria: dropped from an existing table. The
# career-site publication date came from that fact sheet too (not checked in the page): emptied.
FACT_SHEET_COLUMNS = ("detail_summary", "requirements", "city", "country", "seniority", "experience_years",
                      "experience_requirement", "languages", "contract", "workload", "salary", "education",
                      "ad_language")
# Kinds of IT job of the former triage, replaced by the criteria: dropped too
DROPPED_COLUMNS = (*FACT_SHEET_COLUMNS, "category", "secondary_category")
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
    for name, kind in FACT_COLUMNS.items():         # table created before these columns: add them
        if name not in columns:
            conn.execute(f"ALTER TABLE offers ADD COLUMN {name} {kind}")
    dropped = [name for name in DROPPED_COLUMNS if name in columns]
    for name in dropped:
        conn.execute(f"ALTER TABLE offers DROP COLUMN {name}")
    if set(dropped) & set(FACT_SHEET_COLUMNS):
        conn.execute("UPDATE offers SET published = '' WHERE source = 'career_site'")
    conn.commit()
    return conn


def _row(offer: dict) -> tuple:
    def value(name):
        found = offer.get(name)
        if name in NULLABLE_JSON:
            return None if found is None else json.dumps(found, ensure_ascii=False)
        if name in JSON_COLUMNS:
            return json.dumps(found or [], ensure_ascii=False)
        if name == "full_ad":
            return None if found is None else int(found)
        return found if found is not None or name == "score" else ""
    return tuple(value(name) if name != "status" else offer.get("status", "new") for name in COLUMNS)


def row_to_offer(row: sqlite3.Row) -> dict:
    """A stored offer as a dict, JSON columns decoded (for scripts/rescore.py)."""
    offer = dict(row)
    for name in JSON_COLUMNS:
        if name in offer:
            empty = "null" if name in NULLABLE_JSON else "[]"
            offer[name] = json.loads(offer[name] or empty)
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


def _read_only() -> sqlite3.Connection | None:
    """The database opened read only (nothing created, migrated or written), or None when missing."""
    if not config.DB_PATH.exists():
        return None
    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def kept_offers(company: str | None = None, min_score: int | None = None,
                source: str | None = None) -> list[dict]:
    """Kept offers of the whole database (config.DB_PATH), best score first, then the most recently
    first seen, read only. "id": the SQLite rowid (scripts/match_offers.py --offer-id).
    company is matched without case; source exactly ("career_site", or an RSS source name)."""
    conn = _read_only()
    if conn is None:
        return []
    try:
        sql, params = "SELECT rowid AS id, * FROM offers WHERE status = 'new' AND score IS NOT NULL", []
        if company is not None:
            sql += " AND lower(company) = lower(?)"
            params.append(company)
        if min_score is not None:
            sql += " AND score >= ?"
            params.append(min_score)
        if source is not None:
            sql += " AND source = ?"
            params.append(source)
        rows = conn.execute(sql + " ORDER BY score DESC, fetched DESC", params).fetchall()
    finally:
        conn.close()
    return [row_to_offer(row) for row in rows]


def offer_by_id(offer_id: int) -> dict | None:
    """One stored offer by its SQLite rowid, kept or rejected, read only; None when not found."""
    conn = _read_only()
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT rowid AS id, * FROM offers WHERE rowid = ?", (offer_id,)).fetchone()
    finally:
        conn.close()
    return row_to_offer(row) if row else None


def save_requirements(company: str, key: str, items: list, model: str, prompt_id: str) -> None:
    """Store the raw requirements of one offer (untrusted, checked again when read), their model and
    the fingerprint of the instructions that gave them."""
    conn = connect()
    try:
        conn.execute("UPDATE offers SET ad_requirements = ?, ad_requirements_model = ?, ad_requirements_prompt = ? "
                     "WHERE company = ? AND key = ?",
                     (json.dumps(items, ensure_ascii=False), model, prompt_id, company, key))
        conn.commit()
    finally:
        conn.close()

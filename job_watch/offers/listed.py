"""listed_offers table: every offer seen in a company job list, interesting or not.

Only what the listing shows (title, location, link), never the detail of the offer. A new
offer is inserted with first_seen; an offer already known only gets its last_seen updated,
so first_seen tells which offers are new since the previous run.

The offer key (extraction.offer_key) is unique within one company only: a reference number
or a title and location can repeat between companies, so the primary key is (company, key).
"""
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from job_watch import config
from job_watch.list_agent.extraction import CheckedOffer

SCHEMA = """
CREATE TABLE IF NOT EXISTS listed_offers (
    company     TEXT NOT NULL,
    key         TEXT NOT NULL,
    title       TEXT NOT NULL,
    location    TEXT NOT NULL,
    link        TEXT NOT NULL,
    verified    INTEGER NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    kept        INTEGER,            -- 1 kept by the filter, 0 not kept, NULL not filtered
    domain              TEXT,       -- triage (offers.triage), NULL when not triaged or no valid answer
    category            TEXT,       -- Technology/IT only
    secondary_category  TEXT,
    category_reason     TEXT,
    PRIMARY KEY (company, key)
)
"""
ADDED_COLUMNS = {"domain": "TEXT", "category": "TEXT", "secondary_category": "TEXT", "category_reason": "TEXT"}


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the database (config.DB_PATH by default, read at call time) and create the table if needed."""
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.execute(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(listed_offers)")}
    for name, kind in ADDED_COLUMNS.items():        # table created before the triage: add the columns
        if name not in columns:
            conn.execute(f"ALTER TABLE listed_offers ADD COLUMN {name} {kind}")
    conn.commit()
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def known_keys(conn: sqlite3.Connection, company: str) -> set[str]:
    """Keys of the offers of this company already in listed_offers (read only)."""
    return {row[0] for row in conn.execute("SELECT key FROM listed_offers WHERE company = ?", (company,))}


def save_listed_offers(conn: sqlite3.Connection, company: str, offers: list[CheckedOffer], seen: str,
                       keep: Callable[[CheckedOffer], bool] | None = None, commit: bool = True) -> list[str]:
    """Insert the new offers, update last_seen of the known ones. Return the keys of the new offers.

    keep: filter deciding the kept column of new offers (None: not filtered). A known offer
    keeps its stored values: only last_seen changes.
    commit: False to leave the commit to the caller, so that listed_offers and offers are
    written in one transaction (an offer is never known here without being in offers).
    """
    for offer in offers:
        if not offer.key:
            raise ValueError(f"offer without key (deduplicate() not called): {offer.title!r}")
    known = known_keys(conn, company)
    new = [o for o in offers if o.key not in known]
    conn.executemany(
        """
        INSERT INTO listed_offers (company, key, title, location, link, verified, first_seen, last_seen, kept,
                                   domain, category, secondary_category, category_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(company, o.key, o.title, o.location, o.link, int(o.verified), seen, seen,
          None if keep is None else int(keep(o)), o.domain, o.category, o.secondary_category, o.category_reason)
         for o in new],
    )
    conn.executemany(
        "UPDATE listed_offers SET last_seen = ? WHERE company = ? AND key = ?",
        [(seen, company, o.key) for o in offers if o.key in known],
    )
    if commit:
        conn.commit()
    return [o.key for o in new]

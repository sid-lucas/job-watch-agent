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
    PRIMARY KEY (company, key)
)
"""


def connect(path: Path = config.DB_PATH) -> sqlite3.Connection:
    """Open the database and create the table if needed."""
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_listed_offers(conn: sqlite3.Connection, company: str, offers: list[CheckedOffer], seen: str,
                       keep: Callable[[CheckedOffer], bool] | None = None) -> list[str]:
    """Insert the new offers, update last_seen of the known ones. Return the keys of the new offers.

    keep: filter deciding the kept column of new offers (None: not filtered). A known offer
    keeps its stored values: only last_seen changes.
    """
    for offer in offers:
        if not offer.key:
            raise ValueError(f"offer without key (deduplicate() not called): {offer.title!r}")
    known = {row[0] for row in conn.execute(
        "SELECT key FROM listed_offers WHERE company = ?", (company,))}
    new = [o for o in offers if o.key not in known]
    conn.executemany(
        """
        INSERT INTO listed_offers (company, key, title, location, link, verified, first_seen, last_seen, kept)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(company, o.key, o.title, o.location, o.link, int(o.verified), seen, seen,
          None if keep is None else int(keep(o))) for o in new],
    )
    conn.executemany(
        "UPDATE listed_offers SET last_seen = ? WHERE company = ? AND key = ?",
        [(seen, company, o.key) for o in offers if o.key in known],
    )
    conn.commit()
    return [o.key for o in new]

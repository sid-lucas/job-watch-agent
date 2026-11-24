import json
import sqlite3

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    link        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    company     TEXT,
    location    TEXT,
    description TEXT,
    source      TEXT,
    published   TEXT,
    fetched     TEXT,
    score       INTEGER,
    reasons     TEXT,
    status      TEXT
)
"""


def connect() -> sqlite3.Connection:
    """Open the database and create the table if needed."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(SCHEMA)
    return conn


def save_offers(offers: list[dict]) -> int:
    """Insert offers not already in the database. Return the number of new offers."""
    conn = connect()
    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO offers
            (link, title, company, location, description, source,
             published, fetched, score, reasons, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (o["link"], o["title"], o["company"], o["location"], o["description"],
             o["source"], o["published"], o["fetched"], o.get("score"),
             json.dumps(o.get("reasons", [])), o.get("status", "new"))
            for o in offers
        ],
    )
    conn.commit()
    new = conn.total_changes - before
    conn.close()
    return new
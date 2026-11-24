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


def save_offers(offers: list[dict]) -> list[str]:
    """Insert offers not already in the database. Return the links of the new offers."""
    conn = connect()
    existing = {row[0] for row in conn.execute("SELECT link FROM offers")}
    new_offers = [o for o in offers if o["link"] not in existing]

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
            for o in new_offers
        ],
    )
    conn.commit()
    conn.close()
    return [o["link"] for o in new_offers]
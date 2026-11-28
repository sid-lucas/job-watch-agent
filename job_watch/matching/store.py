"""data/personal/matching.db (config.MATCH_DB_PATH): answers of the matching against the profile.

They hold quotes of the profile, so they are personal data: never in offers.db. Only the matching
package opens this file, and only while MATCH_CHAIN holds local models only (checked on every
connection). Key: (company, key) of the offer in offers.db.
"""
import json
import sqlite3
from datetime import datetime

from job_watch import config
from job_watch.llm import local_models

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    company       TEXT NOT NULL,
    key           TEXT NOT NULL,
    match_answers TEXT NOT NULL,     -- JSON, raw answers of the local model (checked again when read)
    match_model   TEXT,
    match_prompt  TEXT,              -- fingerprint: instructions, schema, requirements, profile
    matched       TEXT,              -- date and time of the answers
    PRIMARY KEY (company, key)
)
"""


def connect() -> sqlite3.Connection:
    local_models(config.MATCH_CHAIN)
    config.MATCH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.MATCH_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def stored(company: str, key: str) -> dict | None:
    """Stored answers of one offer: {"answers", "model", "prompt"}, or None."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM matches WHERE company = ? AND key = ?", (company, key)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"answers": json.loads(row["match_answers"]), "model": row["match_model"], "prompt": row["match_prompt"]}


def save(company: str, key: str, answers: dict, model: str, prompt_id: str) -> None:
    conn = connect()
    try:
        conn.execute("INSERT OR REPLACE INTO matches (company, key, match_answers, match_model, match_prompt, matched)"
                     " VALUES (?, ?, ?, ?, ?, ?)",
                     (company, key, json.dumps(answers, ensure_ascii=False), model, prompt_id,
                      datetime.now().isoformat(timespec="seconds")))
        conn.commit()
    finally:
        conn.close()

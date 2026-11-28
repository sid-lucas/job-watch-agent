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
    match_score   REAL,              -- percent, computed in code from the checked answers
    match_blocking TEXT,             -- JSON list of the blocking gaps
    PRIMARY KEY (company, key)
)
"""
ADDED_COLUMNS = {"match_score": "REAL", "match_blocking": "TEXT"}


def connect() -> sqlite3.Connection:
    local_models(config.MATCH_CHAIN)
    config.MATCH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.MATCH_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    for name, kind in ADDED_COLUMNS.items():        # table created before these columns
        if name not in columns:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {name} {kind}")
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


def save(company: str, key: str, answers: dict, model: str, prompt_id: str, score: float,
         blocking: list[str]) -> None:
    """Store the raw answers of one offer and its score (computed again each time it is read)."""
    conn = connect()
    try:
        conn.execute("INSERT OR REPLACE INTO matches (company, key, match_answers, match_model, match_prompt, matched,"
                     " match_score, match_blocking) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (company, key, json.dumps(answers, ensure_ascii=False), model, prompt_id,
                      datetime.now().isoformat(timespec="seconds"), score, json.dumps(blocking, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def update_score(company: str, key: str, score: float, blocking: list[str]) -> None:
    """The score of stored answers computed again (rules or settings changed), answers unchanged."""
    conn = connect()
    try:
        conn.execute("UPDATE matches SET match_score = ?, match_blocking = ? WHERE company = ? AND key = ?",
                     (score, json.dumps(blocking, ensure_ascii=False), company, key))
        conn.commit()
    finally:
        conn.close()


def scores() -> dict[tuple[str, str], tuple[float, list[str]]]:
    """(company, key) -> (match percent, blocking gaps) of every matched offer; empty without a
    matching database (nothing is created)."""
    if not config.MATCH_DB_PATH.exists():
        local_models(config.MATCH_CHAIN)
        return {}
    conn = connect()
    try:
        rows = conn.execute("SELECT company, key, match_score, match_blocking FROM matches "
                            "WHERE match_score IS NOT NULL").fetchall()
    finally:
        conn.close()
    return {(r["company"], r["key"]): (r["match_score"], json.loads(r["match_blocking"] or "[]")) for r in rows}

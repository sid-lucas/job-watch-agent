"""Compare the triage of the local model (qwen) and Gemini on the titles of a listed_offers table.

The database is opened read only; nothing is written. Gemini calls: one per TRIAGE_BATCH_SIZE titles.

    python -u -m scripts.compare_triage /tmp/jw_icrc_rolex.db [--limit N]
"""
import argparse
import sqlite3
from pathlib import Path

from job_watch import config
from job_watch.offers.triage import TriageInput, compare, triage_offers


def load_offers(path: Path, limit: int | None) -> list[TriageInput]:
    """Distinct (title, location, company) of listed_offers, read only."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT DISTINCT title, location, company FROM listed_offers "
                            "ORDER BY company, title").fetchall()
    finally:
        conn.close()
    offers = [TriageInput(title=t, location=l, company=c) for t, l, c in rows]
    return offers[:limit] if limit else offers


def describe(triage) -> str:
    return triage.category + (f" + {triage.secondary}" if triage.secondary else "") + ("" if triage.answered
                                                                                       else " (no valid answer)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--limit", type=int, help="first N titles only")
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit(f"no database at {args.db}")

    offers = load_offers(args.db, args.limit)
    local = tuple(m for m in config.TRIAGE_CHAIN if m[0] == "ollama")
    cloud = tuple(m for m in config.CLOUD_MODELS if m[0] == "gemini")
    print(f"{len(offers)} titles; local {local}, cloud {cloud}", flush=True)

    def log(line):
        print(f"  {line}", flush=True)

    print("qwen:", flush=True)
    first = triage_offers(offers, log=log, models=local)
    print("gemini:", flush=True)
    second = triage_offers(offers, log=log, models=cloud)
    result = compare(offers, first, second)

    n = result.offers or 1
    print(f"\nsame category: {result.same_category}/{result.offers} ({result.same_category / n:.0%}), "
          f"same group: {result.same_group}/{result.offers} ({result.same_group / n:.0%})")
    print(f"\n{len(result.disagreements)} disagreements (title | qwen | gemini):")
    for d in result.disagreements:
        print(f"- {d.title[:80]} [{d.company}]\n    qwen:   {describe(d.first)}\n    gemini: {describe(d.second)}")


if __name__ == "__main__":
    main()

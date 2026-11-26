"""Compare the triage of the local model (qwen) and Gemini on the titles of a listed_offers table.

The database is opened read only; nothing is written. Prints the agreement on the domain and on
what would be kept (Technology/IT or not), the "Other" answers and offers without a valid answer
for each model, the duration of the qwen run, and the offers kept by one model only.

    python -u -m scripts.compare_triage DB [--limit N] [--batch-size N] [--qwen-think]
"""
import argparse
import sqlite3
from pathlib import Path

from job_watch import config
from job_watch.offers.triage import TriageInput, batch_size, compare, timed, triage_offers


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
    if not triage.answered:
        return "(no valid answer)"
    return triage.domain + (f" > {triage.category}" if triage.category else "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--limit", type=int, help="first N titles only")
    parser.add_argument("--batch-size", type=int, help="titles per qwen call (default: TRIAGE_BATCH_SIZE)")
    parser.add_argument("--qwen-think", action="store_true", help="qwen3 reasoning on (slower)")
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit(f"no database at {args.db}")
    config.OLLAMA_THINK = args.qwen_think       # read when the client is built, before any call

    offers = load_offers(args.db, args.limit)
    local = tuple(m for m in config.TRIAGE_CHAIN if m[0] == "ollama")
    cloud = tuple(m for m in config.CLOUD_MODELS if m[0] == "gemini")
    local_size = args.batch_size or batch_size(local)
    print(f"{len(offers)} titles; qwen {local} batch {local_size}, think {args.qwen_think}; "
          f"gemini {cloud} batch {batch_size(cloud)}", flush=True)

    def log(line):
        print(f"  {line}", flush=True)

    print("qwen:", flush=True)
    first, seconds = timed(triage_offers, offers, log=log, models=local, size=local_size)
    print(f"  qwen: {seconds:.0f} s ({seconds / max(len(offers), 1):.1f} s per title)", flush=True)
    print("gemini:", flush=True)
    second = triage_offers(offers, log=log, models=cloud)
    result = compare(offers, first, second)

    n = result.offers or 1
    print(f"\nsame domain: {result.same_domain}/{result.offers} ({result.same_domain / n:.0%}); "
          f"same decision (Technology/IT or not): {result.same_keep}/{result.offers} ({result.same_keep / n:.0%})")
    print(f"'Other': qwen {result.other[0]}, gemini {result.other[1]}; "
          f"no valid answer (kept): qwen {result.no_answer[0]}, gemini {result.no_answer[1]}")
    print(f"qwen run: {seconds:.0f} s for {result.offers} titles")
    print(f"\n{len(result.disagreements)} offers kept by one model only (title | qwen | gemini):")
    for d in result.disagreements:
        print(f"- {d.title[:80]} [{d.company}]\n    qwen:   {describe(d.first)}\n    gemini: {describe(d.second)}")


if __name__ == "__main__":
    main()

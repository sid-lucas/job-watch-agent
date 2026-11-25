"""Collect the offers of one company job list into listed_offers, and print a summary.

    python -u -m scripts.collect_career_site COMPANY URL [--db PATH]     # default: data/offers.db
"""
import argparse
from pathlib import Path

from job_watch import config
from job_watch.list_agent.collect import collect_company
from job_watch.offers.listed import connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("company")
    parser.add_argument("url")
    parser.add_argument("--db", type=Path, default=config.DB_PATH)
    args = parser.parse_args()

    conn = connect(args.db)
    try:
        result = collect_company(args.company, args.url, conn)
    finally:
        conn.close()
    print(f"{result.company}: {len(result.offers)} offers, {len(result.new_keys)} new, "
          f"{len(result.new_kept)} new and kept; pages {result.pages_reached}, stop {result.stop}, "
          f"failed chunks {result.failed_chunks}, {result.seconds}s")
    print("models: " + (", ".join(f"{n} {c}" for n, c in result.model_calls.items()) or "no LLM call"))
    for offer in result.new_kept:
        print(f"  kept: {offer.title[:70]!r} | {offer.location[:30]} | "
              f"{'verified' if offer.verified else 'unverified'} | {offer.link or '-'}")


if __name__ == "__main__":
    main()

"""Compute rejections and scores again from the stored criteria answers (user_config.py), no LLM call.

With --ask, offers without answers to the current questions (a question changed or added, or
stored before the criteria) are asked again: one LLM call each, on the stored text.

    python -u -m scripts.rescore [--db PATH] [--dry-run]       # default: data/offers.db
    python -u -m scripts.rescore --ask --dry-run              # how many LLM calls --ask would make
    python -u -m scripts.rescore --ask
"""
import argparse
from pathlib import Path

from job_watch import config
from job_watch.offers.rescore import rescore, to_ask


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, help=f"database file (default: {config.DB_PATH})")
    parser.add_argument("--dry-run", action="store_true", help="show the changes, write nothing")
    parser.add_argument("--ask", action="store_true",
                        help="ask again the offers without answers to the current questions (LLM calls)")
    args = parser.parse_args()
    if args.db:
        if not args.db.exists():
            raise SystemExit(f"no database at {args.db}")
        config.DB_PATH = args.db

    if args.ask:
        offers, listed_offers = to_ask()
        print(f"--ask: {offers} offers and {listed_offers} listed offers without answers to the current "
              f"questions: {offers + listed_offers} LLM calls")
        if args.dry_run:
            print("dry run: nothing asked, nothing written")
            return
    report = rescore(write=not args.dry_run, ask_missing=args.ask, log=lambda line: print(f"  {line}", flush=True))
    if args.ask:
        print(f"asked: {report.offers_asked} offers, {report.listed_asked} listed offers")
    print(f"offers: {report.offers}, {len(report.offer_changes)} changed, "
          f"{report.offers_not_rescored} not rescored (no answers to the current questions)")
    for change in report.offer_changes:
        print(f"  {change.company}: {change.title[:70]} | {change.before} -> {change.after}")
    print(f"listed offers: {report.listed}, {len(report.listed_changes)} changed, "
          f"{report.listed_not_rescored} not rescored")
    for change in report.listed_changes:
        print(f"  {change.company}: {change.title[:70]} | {change.before} -> {change.after}")
    if report.kept_without_detail:
        print(f"{len(report.kept_without_detail)} listed offers now kept have no detail (set aside before it); "
              "they are not fetched by this script")
    print("dry run: nothing written" if args.dry_run else "written")


if __name__ == "__main__":
    main()

"""Compute rejections and scores again with the current rules (DEALBREAKERS, BONUSES), no LLM call.

    python -m scripts.rescore [--db PATH] [--dry-run]       # default: data/offers.db
"""
import argparse
from pathlib import Path

from job_watch import config
from job_watch.offers.rescore import rescore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, help=f"database file (default: {config.DB_PATH})")
    parser.add_argument("--dry-run", action="store_true", help="show the changes, write nothing")
    args = parser.parse_args()
    if args.db:
        if not args.db.exists():
            raise SystemExit(f"no database at {args.db}")
        config.DB_PATH = args.db

    report = rescore(write=not args.dry_run)
    print(f"offers: {report.offers}, {len(report.offer_changes)} changed")
    for change in report.offer_changes:
        print(f"  {change.company}: {change.title[:70]} | {change.before} -> {change.after}")
    print(f"listed offers: {report.listed}, {len(report.listed_changes)} changed")
    for change in report.listed_changes:
        print(f"  {change.company}: {change.title[:70]} | {change.before} -> {change.after}")
    if report.kept_without_detail:
        print(f"{len(report.kept_without_detail)} listed offers now kept have no detail (set aside before it); "
              "they are not fetched by this script")
    print("dry run: nothing written" if args.dry_run else "written")


if __name__ == "__main__":
    main()

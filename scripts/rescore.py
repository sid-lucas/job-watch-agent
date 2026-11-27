"""Compute rejections and scores again from the stored criteria answers (user_config.py), no LLM call.

With --ask, offers without answers to the current questions (a question changed or added, or
stored before the criteria) are asked again: one LLM call each, on the stored text.

    python -u -m scripts.rescore [--db PATH] [--dry-run]       # default: data/offers.db
    python -u -m scripts.rescore --ask --dry-run              # how many LLM calls --ask would make
    python -u -m scripts.rescore --ask
    python -u -m scripts.rescore --ask --reask-unrecorded --dry-run   # also the answers without a recorded model
    python -u -m scripts.rescore --open-details --dry-run     # pages and LLM calls --open-details would make
    python -u -m scripts.rescore --open-details

--open-details: listed offers that a later change of the criteria keeps again were never opened
(set aside when first seen, so known since): their pages are opened now, with the guardrails of a
run, the criteria asked on the whole ad, and they are stored in offers.
"""
import argparse
from pathlib import Path

from job_watch import config
from job_watch.offers.career_sites import open_missing_details
from job_watch.offers.rescore import rescore, to_ask


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, help=f"database file (default: {config.DB_PATH})")
    parser.add_argument("--dry-run", action="store_true", help="show the changes, write nothing")
    parser.add_argument("--ask", action="store_true",
                        help="ask again the offers without answers to the current questions (LLM calls)")
    parser.add_argument("--reask-unrecorded", action="store_true",
                        help="with --ask: also ask again the offers whose answers carry no model (imported)")
    parser.add_argument("--open-details", action="store_true",
                        help="open the pages of listed offers kept again later, never opened (web, LLM calls)")
    args = parser.parse_args()
    if args.reask_unrecorded and not args.ask:
        parser.error("--reask-unrecorded needs --ask")
    if args.db:
        if not args.db.exists():
            raise SystemExit(f"no database at {args.db}")
        config.DB_PATH = args.db

    if args.ask:
        offers, listed_offers = to_ask(args.reask_unrecorded)
        what = "without answers to the current questions" + (", or answered by an unrecorded model"
                                                             if args.reask_unrecorded else "")
        print(f"--ask: {offers} offers and {listed_offers} listed offers {what}: {offers + listed_offers} LLM calls")
        if args.dry_run:
            print("dry run: nothing asked, nothing written")
            return
    report = rescore(write=not args.dry_run, ask_missing=args.ask, unrecorded=args.reask_unrecorded,
                     log=lambda line: print(f"  {line}", flush=True))
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
    if args.open_details:
        details = open_missing_details(write=not args.dry_run)
        skipped = ", ".join(f"{reason} {count}" for reason, count in sorted(details.skipped.items())) or "none"
        print(f"--open-details: {details.companies} companies, {details.pages_to_open} pages to open "
              f"({details.pages_to_open} LLM calls at most), without detail: {skipped}")
        if details.not_in_registry:
            print(f"  not in the registry (left as they are): {', '.join(details.not_in_registry)}")
        if not args.dry_run:
            print(f"  stored in offers: {details.stored}, deferred to the next run: {details.deferred}")
    print("dry run: nothing written" if args.dry_run else "written")


if __name__ == "__main__":
    main()

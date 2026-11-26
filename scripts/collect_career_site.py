"""Collect the offers of one company job list and print a summary (try run: nothing is written).
"New" means not yet in listed_offers of the database. With --details, also open the pages of the
new offers kept and print what was extracted. To store offers, use main.py: it writes listed_offers
and offers together.

    python -u -m scripts.collect_career_site COMPANY URL [--db PATH] [--details]   # default: data/offers.db
"""
import argparse
from pathlib import Path

from job_watch import config
from job_watch.list_agent.collect import collect_company, collect_details
from job_watch.offers.listed import connect


def log(line: str) -> None:
    print(f"  {line}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("company")
    parser.add_argument("url")
    parser.add_argument("--db", type=Path, default=config.DB_PATH)
    parser.add_argument("--details", action="store_true", help="open the pages of the new offers kept")
    args = parser.parse_args()

    conn = connect(args.db)
    try:
        result = collect_company(args.company, args.url, conn, log=log)
    finally:
        conn.close()
    print(f"{result.company}: {len(result.offers)} offers, {len(result.new_keys)} new, "
          f"{len(result.new_kept)} new and kept; pages {result.pages_reached}, stop {result.stop}, "
          f"failed chunks {result.failed_chunks}, {result.seconds}s")
    print("models: " + (", ".join(f"{n} {c}" for n, c in result.model_calls.items()) or "no LLM call"))
    for offer in result.new_kept:
        print(f"  kept: {offer.title[:70]!r} | {offer.location[:30]} | "
              f"{'verified' if offer.verified else 'unverified'} | {offer.link or '-'}")
    if not args.details:
        return

    details = collect_details(result, log=log)
    print(f"\ndetails: {len(details.details)} extracted, {len(details.refused_pages)} pages refused, "
          f"{len(details.failed_extractions)} extractions failed, {len(details.skipped)} offers not opened")
    print("models: " + (", ".join(f"{n} {c}" for n, c in details.model_calls.items()) or "no LLM call"))
    for skipped in details.skipped:
        print(f"  not opened: {skipped.title[:60]!r} {skipped.reason}")
    for page in details.refused_pages:
        print(f"  refused: {page.key} {page.failure} ({page.detail})")
    for d in details.details:
        languages = ", ".join(f"{n['language']} {n['level']}" for n in d.languages) or "-"
        print(f"  {d.key}: {d.city}, {d.country}; {d.seniority}; {d.contract}"
              f"{' (doubtful)' if d.contract_doubtful else ''}, {d.workload or '-'}; "
              f"experience {d.experience_years or '-'} {d.experience_requirement}; languages {languages}; "
              f"education {d.education}; salary {d.salary or '-'}; posted {d.posted or '-'}; "
              f"{len(d.requirements)} requirements ({d.dropped_requirements} dropped)"
              + (f"; not supported by the page: {', '.join(d.unchecked)}" if d.unchecked else ""))


if __name__ == "__main__":
    main()

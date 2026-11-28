"""Matching of stored offers against the profile (step 2). Brick 1 only for now: the requirements
of the ad, extracted by the local model of MATCH_CHAIN and checked in code. Read only on the database.

    python -u -m scripts.match_offers --requirements-only --top 3     # best kept offers (as show_offers)
    python -u -m scripts.match_offers --requirements-only --offer-id 42
"""
import argparse
import time
from pathlib import Path

from job_watch import config
from job_watch.llm import local_models
from job_watch.matching.requirements import extract_requirements
from job_watch.offers import storage
from job_watch.offers.scoring import offer_query


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requirements-only", action="store_true", help="extract and show the requirements")
    parser.add_argument("--top", type=int, default=3, help="best kept offers, as show_offers (default: 3)")
    parser.add_argument("--offer-id", type=int, help="one stored offer by its id (shown in this output)")
    parser.add_argument("--db", type=Path, help=f"database file (default: {config.DB_PATH})")
    args = parser.parse_args(argv)
    if not args.requirements_only:
        parser.error("only --requirements-only exists for now (matching against the profile comes next)")
    if args.top < 1:
        parser.error("--top must be at least 1")
    if args.db:
        config.DB_PATH = args.db
    models = local_models(config.MATCH_CHAIN)       # stops here if the chain holds a cloud model

    if args.offer_id is not None:
        found = storage.offer_by_id(args.offer_id)
        if found is None:
            raise SystemExit(f"No offer with id {args.offer_id} in {config.DB_PATH}")
        offers = [found]
    else:
        offers = storage.kept_offers(min_score=config.MIN_SCORE)[:args.top]
    print(f"{len(offers)} offer(s), models {', '.join(f'{p}:{m}' for p, m in models)}, "
          f"reasoning {'on (2 calls per offer)' if config.MATCH_THINK else 'off'}")
    for offer in offers:
        print(f"\n#{offer['id']}  {offer['score']}  {offer['title']} @ {offer['company']}  [{offer['source']}]")
        if not (offer.get("description") or "").strip():
            print("      no ad text stored: nothing to extract")
            continue
        start = time.monotonic()
        extraction = extract_requirements(offer_query(offer))
        took = f"{time.monotonic() - start:.0f}s"
        if extraction.failed:
            print(f"      every model failed ({took})")
            continue
        print(f"      {len(extraction.requirements)} requirements, {len(extraction.dropped)} dropped"
              f" | {extraction.model} {took}")
        for r in extraction.requirements:
            print(f"      {r.kind:4} {r.category:13} {r.label:28} '{r.quote}'")
        for d in extraction.dropped:
            print(f"      dropped ({d.reason}): {d.item}")


if __name__ == "__main__":
    main()

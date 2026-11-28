"""Matching of stored offers against the profile (step 2). Brick 1 only for now: the requirements
of the ad (public data: MODEL_CHAIN, local model as fallback), checked in code. They are stored
with the offer and reused on the next run (--refresh extracts them again); nothing else is written.

    python -u -m scripts.match_offers --requirements-only --top 3     # best kept offers (as show_offers)
    python -u -m scripts.match_offers --requirements-only --offer-id 42 --refresh
"""
import argparse
import time
from pathlib import Path

from job_watch import config
from job_watch.llm import llm_chain
from job_watch.matching.requirements import requirements_of
from job_watch.offers import storage


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requirements-only", action="store_true", help="extract and show the requirements")
    parser.add_argument("--top", type=int, default=3, help="best kept offers, as show_offers (default: 3)")
    parser.add_argument("--offer-id", type=int, help="one stored offer by its id (shown in this output)")
    parser.add_argument("--refresh", action="store_true", help="extract again, even if stored")
    parser.add_argument("--db", type=Path, help=f"database file (default: {config.DB_PATH})")
    args = parser.parse_args(argv)
    if not args.requirements_only:
        parser.error("only --requirements-only exists for now (matching against the profile comes next)")
    if args.top < 1:
        parser.error("--top must be at least 1")
    if args.db:
        config.DB_PATH = args.db

    if args.offer_id is not None:
        found = storage.offer_by_id(args.offer_id)
        if found is None:
            raise SystemExit(f"No offer with id {args.offer_id} in {config.DB_PATH}")
        offers = [found]
    else:
        offers = storage.kept_offers(min_score=config.MIN_SCORE)[:args.top]
    print(f"{len(offers)} offer(s), models {', '.join(f'{p}:{m}' for p, m in llm_chain())}; local fallback: "
          f"reasoning {'on (2 calls)' if config.MATCH_THINK else 'off'}, at most {config.MATCH_TIMEOUT}s per call")
    for offer in offers:
        print(f"\n#{offer['id']}  {offer['score']}  {offer['title']} @ {offer['company']}  [{offer['source']}]")
        if not (offer.get("description") or "").strip():
            print("      no ad text stored: nothing to extract")
            continue
        start = time.monotonic()
        extraction = requirements_of(offer, refresh=args.refresh, log=lambda line: print(f"      {line}", flush=True))
        took = f"{time.monotonic() - start:.0f}s"
        if extraction.failure:
            print(f"      failed ({extraction.failure}) after {took}: next offer")
            continue
        source = "stored, checked again" if extraction.reused else took
        print(f"      {len(extraction.requirements)} requirements, {len(extraction.dropped)} dropped"
              f" | {extraction.model} {source}")
        for r in extraction.requirements:
            print(f"      {r.kind:4} {r.category:13} {r.label:28} '{r.quote}'")
        for d in extraction.dropped:
            print(f"      dropped ({d.reason}): {d.item}")


if __name__ == "__main__":
    main()

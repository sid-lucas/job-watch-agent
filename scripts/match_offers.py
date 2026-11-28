"""Matching of stored offers against the profile (step 2).

Brick 1, the requirements of the ad (public data: REQUIREMENTS_CHAIN, local fallback), stored with
the offer in offers.db. Brick 2, each requirement compared with data/personal/profile.md (personal
data: MATCH_CHAIN, local models only), stored in data/personal/matching.db. Stored results are
reused; --refresh asks again (the requirements with --requirements-only, else the comparison).

    python -u -m scripts.match_offers --top 3                          # match % and gaps, per offer
    python -u -m scripts.match_offers --top 3 --details                # every requirement with its proof
    python -u -m scripts.match_offers --requirements-only --top 3      # requirements only
    python -u -m scripts.match_offers --offer-id 42 --refresh
"""
import argparse
import time
from pathlib import Path

from job_watch import config
from job_watch.llm import llm_chain
from collections import Counter

from job_watch.matching.compare import Matched, Matching, match_offer
from job_watch.matching.profile import read_profile
from job_watch.matching.requirements import Requirement, requirements_of
from job_watch.offers import storage


def describe(r: Requirement) -> str:
    """Label with its options, years and level: "Python (Python | Go, 3+ y)"."""
    extra = [" | ".join(r.options)] if r.options else []
    extra += [f"{r.min_years}+ y"] if r.min_years is not None else []
    extra += [r.level] if r.level else []
    return r.label + (f" ({', '.join(extra)})" if extra else "")


def show_match(m: Matched) -> None:
    option = f" [{m.option}]" if m.option else ""
    line = f"{m.line.id} {m.line.text[:70]}" if m.line else "-"
    print(f"      {m.kind:4} {m.verdict:8} {m.level.text():18} {(m.label + option)[:40]:40} {line}")
    if m.reason:
        print(f"           {m.reason}")
    for note in m.notes:
        print(f"           code: {note}")


VERDICTS = ("covered", "partial", "missing", "unknown")


def show_summary(offer: dict, matching: Matching) -> None:
    """Match %, step 1 score, counts by kind, strengths and gaps."""
    print(f"      match {matching.score.percent:.0f}% | step 1 score {offer['score']}")
    for kind in ("must", "nice"):
        counts = Counter(m.verdict for m in matching.results if m.kind == kind)
        print(f"      {kind}: " + ", ".join(f"{counts[v]} {v}" for v in VERDICTS))
    def labels(results):
        return ", ".join(m.label + (f" [{m.option}]" if m.option else "") for m in results) or "-"
    must_covered = [m for m in matching.results if m.kind == "must" and m.verdict == "covered"]
    strengths = sorted(must_covered, key=lambda m: m.category == "soft_skill")[:3]
    print(f"      strengths: {labels(strengths)}")
    print(f"      must gaps: {labels(m for m in matching.results if m.kind == 'must' and m.verdict == 'missing')}")
    if matching.score.blocking:
        print(f"      BLOCKING: {'; '.join(matching.score.blocking)}")
    print(f"      nice gaps: {labels(m for m in matching.results if m.kind == 'nice' and m.verdict == 'missing')}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requirements-only", action="store_true", help="extract and show the requirements only")
    parser.add_argument("--top", type=int, default=3, help="best kept offers, as show_offers (default: 3)")
    parser.add_argument("--offer-id", type=int, help="one stored offer by its id (shown in this output)")
    parser.add_argument("--refresh", action="store_true", help="ask again, even if stored")
    parser.add_argument("--details", action="store_true", help="every requirement with its verdict and proof")
    parser.add_argument("--db", type=Path, help=f"database file (default: {config.DB_PATH})")
    args = parser.parse_args(argv)
    if args.top < 1:
        parser.error("--top must be at least 1")
    if args.db:
        config.DB_PATH = args.db
    profile = None if args.requirements_only else read_profile()    # stops here on a cloud model in MATCH_CHAIN

    if args.offer_id is not None:
        found = storage.offer_by_id(args.offer_id)
        if found is None:
            raise SystemExit(f"No offer with id {args.offer_id} in {config.DB_PATH}")
        offers = [found]
    else:
        offers = storage.kept_offers(min_score=config.MIN_SCORE)[:args.top]
    print(f"{len(offers)} offer(s); requirements: {', '.join(m for _, m in llm_chain(config.REQUIREMENTS_CHAIN))}"
          + ("" if profile is None else f"; profile: {', '.join(m for _, m in llm_chain(config.MATCH_CHAIN))} "
                                         f"(local only, reasoning {'on' if config.MATCH_THINK else 'off'})"))
    log = lambda line: print(f"      {line}", flush=True)     # noqa: E731
    for offer in offers:
        print(f"\n#{offer['id']}  {offer['score']}  {offer['title']} @ {offer['company']}  [{offer['source']}]")
        if not (offer.get("description") or "").strip():
            print("      no ad text stored: nothing to extract")
            continue
        start = time.monotonic()
        extraction = requirements_of(offer, refresh=args.refresh and profile is None, log=log)
        took = f"{time.monotonic() - start:.0f}s"
        if extraction.failure:
            print(f"      requirements failed ({extraction.failure}) after {took}: next offer")
            continue
        source = "stored, checked again" if extraction.reused else took
        print(f"      {len(extraction.requirements)} requirements, {len(extraction.dropped)} dropped"
              f" | {extraction.model} {source}")
        if profile is None:
            for r in extraction.requirements:
                print(f"      {r.kind:4} {r.category:13} {describe(r):40} '{r.quote}'")
            for note in extraction.notes:
                print(f"      corrected: {note}")
            for d in extraction.dropped:
                print(f"      dropped ({d.reason}): {d.item}")
            continue
        if not extraction.requirements:
            print("      no requirement: nothing to compare")
            continue
        start = time.monotonic()
        matching = match_offer(offer, extraction.requirements, profile, refresh=args.refresh, log=log)
        took = f"{time.monotonic() - start:.0f}s"
        if matching.failure:
            print(f"      comparison failed ({matching.failure}) after {took}: next offer")
            continue
        print(f"      compared with the profile | {matching.model} {'stored, checked again' if matching.reused else took}")
        show_summary(offer, matching)
        if args.details:
            for result in matching.results:
                show_match(result)


if __name__ == "__main__":
    main()

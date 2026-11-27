"""Show the best kept offers of the whole database, not only the new ones (read only, no LLM call).

Same format as the end of main.py: score, reasons with their quotes, location, links. Best score
first, then the most recently first seen.

    python -m scripts.show_offers                          # top 25, score >= MIN_SCORE
    python -m scripts.show_offers --top 50 --min-score 0
    python -m scripts.show_offers --company "Lombard Odier" --source career_site
"""
import argparse
from pathlib import Path

from job_watch import config
from job_watch.offers import storage
from job_watch.offers.display import print_offer


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=25, help="number of offers shown (default: 25)")
    parser.add_argument("--company", help="one company only (case ignored)")
    parser.add_argument("--min-score", type=int, default=config.MIN_SCORE,
                        help=f"lowest score shown (default: MIN_SCORE, {config.MIN_SCORE})")
    parser.add_argument("--source", help="career_site, or an RSS source name")
    parser.add_argument("--db", type=Path, help=f"database file (default: {config.DB_PATH})")
    args = parser.parse_args(argv)
    if args.top < 1:
        parser.error("--top must be at least 1")
    if args.db:
        config.DB_PATH = args.db

    offers = storage.kept_offers(company=args.company, min_score=args.min_score, source=args.source)
    print(f"{len(offers)} kept offers with score >= {args.min_score}"
          + (f" at {args.company}" if args.company else "") + (f" from {args.source}" if args.source else "")
          + (f", the best {args.top}:" if len(offers) > args.top else ":" if offers else "."))
    for offer in offers[:args.top]:
        print_offer(offer)
    if len(offers) > args.top:
        print(f"\n... and {len(offers) - args.top} more (--top)")


if __name__ == "__main__":
    main()

"""job-watch: collect offers (RSS feed and career sites of the registry), filter, score, store, show.

    python main.py                                              # RSS and every career site of the registry
    python main.py --sources rss                                # RSS only (V1)
    python main.py --sources career_sites --companies "Lombard Odier,ICRC"
    python main.py --db /tmp/try.db --registry /tmp/registry.json   # other database and registry
"""
import argparse
from collections import Counter
from pathlib import Path
from urllib.parse import quote_plus

from job_watch import config
from job_watch.offers.graph import build_graph

SOURCES = ("rss", "career_sites")


def search_link(offer: dict) -> str:
    """Build a web search link to find the offer on the company's own site."""
    return "https://www.google.com/search?q=" + quote_plus(f"{offer['company']} {offer['title']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", default=",".join(SOURCES),
                        help="comma-separated: rss, career_sites (default: both)")
    parser.add_argument("--companies", help="comma-separated registry companies (default: every 'ok' entry)")
    parser.add_argument("--db", type=Path, help=f"database file (default: {config.DB_PATH})")
    parser.add_argument("--registry", type=Path, help=f"career sites registry (default: {config.REGISTRY_PATH})")
    args = parser.parse_args(argv)
    args.sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = set(args.sources) - set(SOURCES)
    if unknown:
        parser.error(f"unknown source(s): {', '.join(sorted(unknown))}")
    args.companies = [c.strip() for c in args.companies.split(",") if c.strip()] if args.companies else None
    return args


def show(result: dict) -> None:
    """Print the new offers of the run, best scores first, as in V1."""
    new_pairs = set(map(tuple, result.get("new_offers", [])))
    new_offers = [o for o in result["offers"] if (o["company"], o["key"]) in new_pairs]
    if not new_offers:
        print("\nNo new offers since last run.")
        return

    kept = [o for o in new_offers if o["status"] == "new"]
    rejected = [o for o in new_offers if o["status"] == "rejected"]
    good = sorted((o for o in kept if o["score"] >= config.MIN_SCORE),
                  key=lambda o: o["score"], reverse=True)

    print(f"\n{len(new_offers)} new offers: {len(good)} above score {config.MIN_SCORE}, "
          f"{len(kept) - len(good)} below, {len(rejected)} rejected")

    for o in good[:config.MAX_DISPLAY]:
        print(f"\n{o['score']:4d}  {o['title']} @ {o['company']}  [{o['source']}]")
        print(f"      {', '.join(o['reasons'])}")
        if o.get("contract") or o.get("workload"):
            print(f"      {o.get('location', '')}, {o.get('contract') or '-'}, {o.get('workload') or '-'}")
        if o["link"]:
            print(f"            Offer:  {o['link']}")
        else:
            print(f"            List:   {o.get('list_url', '-')}  (no own link for this offer)")
        print(f"            Search: {search_link(o)}")

    if len(good) > config.MAX_DISPLAY:
        print(f"\n... and {len(good) - config.MAX_DISPLAY} more above score {config.MIN_SCORE}")

    if rejected:
        reasons = Counter(r for o in rejected for r in o["reasons"])
        print("\nRejection reasons: " + ", ".join(f"{r} ({n})" for r, n in reasons.most_common()))


def main(argv: list[str] | None = None) -> dict:
    args = parse_args(argv)
    if args.db:
        config.DB_PATH = args.db
    if args.registry:
        config.REGISTRY_PATH = args.registry
    state = {"offers": [], "sources": args.sources}
    if args.companies:
        state["companies"] = args.companies
    result = build_graph().invoke(state)
    show(result)
    return result


if __name__ == "__main__":
    main()

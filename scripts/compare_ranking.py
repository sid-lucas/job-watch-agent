"""Score stored offers with the criteria of user_config.py and compare with their stored score (read only).

One LLM call per offer (DETAIL_CHAIN); nothing is written to the database.

    python -u -m scripts.compare_ranking --limit 3             # the 3 best stored scores
    python -u -m scripts.compare_ranking --limit 3 --source career_site
"""
import argparse
import sqlite3
from datetime import date, datetime

from job_watch import config
from job_watch.offers import storage
from job_watch.offers.ask_criteria import OfferInput, answer_offer
from job_watch.offers.criteria import judge


def posted_date(published: str) -> date | None:
    try:
        return datetime.fromisoformat(published).date() if published else None
    except ValueError:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3, help="number of offers (one LLM call each)")
    parser.add_argument("--source", help="only this source (career_site, swissdevjobs)")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM offers WHERE status = 'new'" + (" AND source = ?" if args.source else "")
    rows = conn.execute(query + " ORDER BY score DESC LIMIT ?",
                        (*([args.source] if args.source else []), args.limit)).fetchall()
    conn.close()

    settings, today = config.SETTINGS, date.today()
    for number, row in enumerate(rows, 1):
        offer = storage.row_to_offer(row)
        # Career-site description: the text of the offer page. RSS description: not known to be the whole ad
        full_ad = offer["source"] == "career_site" and bool(offer["description"])
        query = OfferInput(company=offer["company"], title=offer["title"],
                           location=offer.get("city") or offer.get("location") or "", ad=offer["description"] or "")
        checked, answered = answer_offer(settings, query, full_ad=full_ad)
        verdict = judge(settings, checked, offer["company"], posted_date(offer["published"]), today)

        print(f"\n[{number}/{len(rows)}] {offer['title'][:70]} @ {offer['company']}  [{offer['source']}]"
              f"  ad: {len(offer['description'] or '')} chars{'' if full_ad else ', not a full ad'}")
        print(f"  stored: {offer['status']} {offer['score']}  {', '.join(offer['reasons'])}")
        if not answered:
            print("  criteria: every model failed, all answers unknown")
        print(f"  new:    {verdict.status} {verdict.score}")
        for reason in verdict.reasons:
            print(f"          {reason}")
        refused = [a for a in checked if a.answer == "unknown" and a.quote and not a.quote_found]
        for answer in refused:
            print(f"  quote not found: {answer.ask[:60]!r} <- {answer.quote[:80]!r}")


if __name__ == "__main__":
    main()

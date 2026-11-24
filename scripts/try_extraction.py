"""Try the offer extraction on a few job lists of different kinds (one LLM call each)."""
from job_watch.llm import call_with_retry
from job_watch.offers.extract import MAX_CHARS, extract_offers
from job_watch.web.browser import render_page

PAGES = [
    ("Lombard Odier", "https://lombardodier.wd3.myworkdayjobs.com/Lombard_Odier_Careers"),   # Workday
    ("SCRT", "https://careers.smartrecruiters.com/SCRT"),                                    # SmartRecruiters
    ("BCN", "https://www.bcn.ch/la-bcn/carrieres/postes-ouverts"),                          # static page
    ("ICRC", "https://careers.icrc.org/go/All-Jobs/3807301/"),                              # SuccessFactors-like site
]


def main():
    for company, url in PAGES:
        page = render_page(url, max_chars=MAX_CHARS)
        if page is None:
            print(f"\n{company}: page not allowed or failed to load")
            continue
        result = call_with_retry(extract_offers, company, page)
        if result is None:
            print(f"\n{company}: LLM unavailable")
            continue
        with_link = sum(1 for o in result.offers if o.link)
        print(f"\n{company}: {len(result.offers)} offers ({with_link} with link), "
              f"more pages: {result.more_pages}, page text: {len(page['text'])} chars, {len(page['links'])} links")
        for offer in result.offers[:8]:
            print(f"  - {offer.title[:60]:60} | {offer.location[:20]:20} | {offer.link or '(no link)'}")


if __name__ == "__main__":
    main()
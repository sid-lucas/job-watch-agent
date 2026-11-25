"""V1 node fetch_career_sites: the list agent and the detail phase for each company of the registry.

Each company with status "ok" and a jobs_url is collected (list agent, extraction, listed_offers,
filter), then the new offers kept by the filter go through the detail phase. They become V1
offers (source "career_site") and follow the same funnel as RSS offers: keywords, duplicates,
flags and score, storage, display. An offer without detail is still stored and scored on its
title, company and location.

A company that fails is logged and skipped: the others are still collected.
"""
import traceback
from datetime import datetime, timezone

from job_watch.list_agent.collect import CompanyCollection, DetailCollection, collect_company, collect_details
from job_watch.offers.listed import connect as connect_listed
from job_watch.offers.nodes import wants
from job_watch.offers.state import JobState, Offer
from job_watch.registry.store import load_registry

SOURCE = "career_site"


def registry_companies(registry: dict, only: list[str] | None = None) -> list[tuple[str, str]]:
    """(company, jobs_url) of the registry entries that can be collected, in registry order."""
    wanted = None if only is None else {name.casefold() for name in only}
    return [(company, entry["jobs_url"]) for company, entry in registry.items()
            if entry.get("status") == "ok" and entry.get("jobs_url")
            and (wanted is None or company.casefold() in wanted)]


def to_offers(collection: CompanyCollection, details: DetailCollection, fetched: str) -> list[Offer]:
    """New offers kept by the filter, as V1 offers, with their detail when the page was read."""
    by_key = {d.key: d for d in details.details}
    offers = []
    for listed in collection.new_kept:
        offer = Offer(key=listed.key, title=listed.title, company=collection.company, location=listed.location,
                      description="", source=SOURCE, link=listed.link, published="", fetched=fetched,
                      list_url=collection.url)
        if detail := by_key.get(listed.key):
            offer.update(description=details.texts.get(listed.key, ""), published=detail.posted,
                         detail_summary=detail.summary, requirements=detail.requirements,
                         contract=detail.contract, workload=detail.workload, ad_language=detail.ad_language,
                         required_languages=list(detail.required_languages))
        offers.append(offer)
    return offers


def log(line: str) -> None:
    print(f"    {line}", flush=True)


def fetch_career_sites(state: JobState) -> dict:
    """Node: collect each company of the registry, then add its new kept offers to the state."""
    offers = list(state.get("offers", []))
    if not wants(state, "career_sites"):
        print("fetch_career_sites: skipped")
        return {"offers": offers}
    companies = registry_companies(load_registry(), state.get("companies"))
    print(f"fetch_career_sites: {len(companies)} companies", flush=True)
    fetched = datetime.now(timezone.utc).isoformat()
    conn = connect_listed()
    try:
        for number, (company, url) in enumerate(companies, 1):
            print(f"  [{number}/{len(companies)}] {company}: {url}", flush=True)
            try:
                collection = collect_company(company, url, conn, log=log)
                log(f"{len(collection.offers)} offers listed, {len(collection.new_keys)} new, "
                    f"{len(collection.new_kept)} new and kept; stop {collection.stop}, "
                    f"failed chunks {collection.failed_chunks}")
                details = collect_details(collection, log=log)
                found = to_offers(collection, details, fetched)
                log(f"{len(details.details)} detailed, {len(found) - len(details.details)} without detail")
                offers += found
            except Exception as error:      # one company must not stop the others
                print(f"  [{number}/{len(companies)}] {company}: FAILED {type(error).__name__}: {error}",
                      flush=True)
                traceback.print_exc(limit=3)
    finally:
        conn.close()
    return {"offers": offers}

"""V1 node fetch_career_sites: the list agent and the detail phase for each company of the registry.

Each company with status "ok" and a jobs_url is collected (list agent, extraction, listed_offers,
filter), then the new offers kept by the filter go through the detail phase. They become V1
offers (source "career_site") and follow the same funnel as RSS offers: keywords, duplicates,
flags and score, storage, display. An offer without detail is still stored and scored on its
title, company and location.

A company that fails is logged and skipped: the others are still collected. Nothing is
written here: save_results stores the offers and listed_offers together, at the end.
"""
import difflib
import traceback
from datetime import datetime, timezone

from job_watch.list_agent.collect import CompanyCollection, DetailCollection, collect_company, collect_details
from job_watch.offers.dates import posted_in_text
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


def why_not_collected(registry: dict, requested: list[str]) -> list[str]:
    """One line per requested company that registry_companies() leaves out, with the reason."""
    by_name = {name.casefold(): name for name in registry}
    lines = []
    for wanted in requested:
        name = by_name.get(wanted.casefold())
        if name is None:
            keys = difflib.get_close_matches(wanted.casefold(), list(by_name), n=3, cutoff=0.6)
            keys += [k for k in by_name if wanted.casefold() in k and k not in keys]     # "Rolex" in "Rolex SA"
            hint = f"; close names: {', '.join(by_name[k] for k in keys[:3])}" if keys else ""
            lines.append(f"{wanted}: not in the registry{hint}")
            continue
        entry = registry[name]
        if entry.get("status") != "ok":
            lines.append(f"{name}: registry status {entry.get('status')!r} (only 'ok' is collected)")
        elif not entry.get("jobs_url"):
            lines.append(f"{name}: no jobs_url in the registry")
    return lines


def to_offers(collection: CompanyCollection, details: DetailCollection, fetched: str) -> list[Offer]:
    """New offers kept by the filter, as V1 offers: the criteria answered on the page when it was
    read, else those answered on the listing data. The page text is kept as the description."""
    by_key = {d.key: d for d in details.details}
    offers = []
    for listed in collection.new_kept:
        text = details.texts.get(listed.key, "")
        posted = posted_in_text(text, datetime.fromisoformat(fetched).date()) if text else None
        offer = Offer(key=listed.key, title=listed.title, company=collection.company, location=listed.location,
                      description=text, source=SOURCE, link=listed.link,
                      published=posted.isoformat() if posted else "",
                      fetched=fetched, list_url=collection.url, domain=listed.domain)
        asked = by_key[listed.key].asked if listed.key in by_key else listed.asked
        if asked is not None:
            offer.update(asked.model_dump())
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
    registry = load_registry()
    companies = registry_companies(registry, state.get("companies"))
    print(f"fetch_career_sites: {len(companies)} companies", flush=True)
    for line in why_not_collected(registry, state.get("companies") or []):
        print(f"  not collected: {line}", flush=True)
    fetched = datetime.now(timezone.utc).isoformat()
    collections = list(state.get("collections", []))
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
                # A page whose criteria wait for the next run: the offer stays new (not saved)
                collection.deferred += details.deferred
                collection.new_kept = [o for o in collection.new_kept if o.key not in details.deferred]
                found = to_offers(collection, details, fetched)
                log(f"{len(details.details)} detailed, {len(found) - len(details.details)} without detail")
                offers += found
                collections.append(collection)
            except Exception as error:      # one company must not stop the others
                print(f"  [{number}/{len(companies)}] {company}: FAILED {type(error).__name__}: {error}",
                      flush=True)
                traceback.print_exc(limit=3)
    finally:
        conn.close()
    # listed_offers is written by save_results, with the offers (one transaction)
    return {"offers": offers, "collections": collections}

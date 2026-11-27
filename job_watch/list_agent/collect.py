"""Collect the offers of one company job list: agent navigation, extraction by the code,
listed_offers table and filter, then the detail phase on the new offers kept.

Nothing is written here: save_collection() writes listed_offers, and the V1 node save_results
calls it in the same transaction as the offers table, so that an offer is never marked as
seen without being stored (a crash in between would otherwise lose it: not new next time).
Offers found are kept even when some chunks failed (the report says so). Offers no longer
listed are not marked here: the judge compares the total announced by the page later.
"""
import sqlite3
from collections.abc import Callable

from pydantic import BaseModel

from job_watch.list_agent import run as agent_run
from job_watch.list_agent.detail import DetailPage, Skipped, open_details, plan_details
from job_watch.list_agent.extraction import CheckedOffer, extract_observations
from job_watch.llm import calls_since, model_calls
from job_watch.offers.listed import known_keys, now_iso, save_listed_offers
from job_watch.offers.ask_criteria import OfferInput
from job_watch.offers.scoring import Asked, ask, domain_kept, screen_listed
from job_watch.offers.triage import TriageInput, triage_offers


class CompanyCollection(BaseModel):
    company: str
    url: str
    stop: str                       # agent stop reason (not trusted: see the judge)
    pages_reached: int
    offers: list[CheckedOffer]      # every offer of this run, checked and deduplicated
    new_keys: list[str]             # offers not yet in listed_offers
    seen: str                       # time of the run, written as first_seen / last_seen
    new_kept: list[CheckedOffer]    # new offers kept by the filter: candidates for the detail phase
    deferred: list[str] = []        # new offers whose criteria wait for the next run: never saved, still new
    failed_chunks: int
    model_calls: dict[str, int]
    seconds: float


def collect_company(company: str, url: str, conn: sqlite3.Connection,
                    log: Callable[[str], None] | None = None) -> CompanyCollection:
    """Run the list agent, extract and check the offers, compare them with listed_offers (read only).

    log: optional, receives progress lines (one per agent turn, one per observation extracted).
    """
    before = model_calls()
    if log:
        run = agent_run.run_list_agent(url, company, on_update=agent_run.progress_printer(log))
    else:
        run = agent_run.run_list_agent(url, company)
    extraction = extract_observations(company, run.observations, log=log)
    known = known_keys(conn, company)
    new_keys = [o.key for o in extraction.offers if o.key not in known]
    new = set(new_keys)
    # Triage of the new offers only (known ones were triaged when first seen)
    to_triage = [o for o in extraction.offers if o.key in new]
    verdicts = triage_offers([TriageInput(title=o.title, location=o.location, company=company) for o in to_triage],
                             log=log)
    for offer, verdict in zip(to_triage, verdicts):
        offer.domain, offer.triage_reason = verdict.domain, verdict.reason
    # Domain, then the criteria on the listing data (one LLM call per offer whose domain is kept)
    total = sum(domain_kept(o.domain) for o in to_triage)
    deferred, number = [], 0
    for offer in to_triage:
        if domain_kept(offer.domain):
            number += 1
        if not screen_listed(offer, company, log=log, progress=f"{number}/{total}"):
            deferred.append(offer.key)
    if log and to_triage:
        log(f"criteria on the listing: {sum(o.asked is not None for o in to_triage)} offers asked, "
            f"{sum(bool(o.rejected_by) for o in to_triage)} set aside, {len(deferred)} deferred to the next run")
    new_keys = [key for key in new_keys if key not in deferred]
    return CompanyCollection(
        company=company, url=url, stop=run.stop, pages_reached=agent_run.pages_reached(run.trail),
        offers=extraction.offers, new_keys=new_keys, seen=now_iso(), deferred=deferred,
        new_kept=[o for o in extraction.offers if o.key in new_keys and keep(o)],
        failed_chunks=extraction.failed_chunks, model_calls=calls_since(before), seconds=run.seconds,
    )


def save_collection(conn: sqlite3.Connection, collection: CompanyCollection, commit: bool = True) -> list[str]:
    """Write the offers of a collection in listed_offers (new ones inserted, known ones: last_seen).
    Deferred offers are left out: they stay new for the next run."""
    offers = [o for o in collection.offers if o.key not in collection.deferred]
    return save_listed_offers(conn, collection.company, offers, collection.seen, keep=keep, commit=commit)


def keep(offer: CheckedOffer) -> bool:
    """A listed offer is kept unless its domain or a reject criterion set it aside."""
    return not offer.rejected_by


class DetailAnswers(BaseModel):
    key: str
    asked: Asked                        # criteria answered on the page text


class DetailCollection(BaseModel):
    company: str
    details: list[DetailAnswers]        # accepted pages, criteria answered
    texts: dict[str, str]               # offer key -> raw page text (cut), for V2
    refused_pages: list[DetailPage]     # not allowed, redirected, title not found
    failed_extractions: list[str]       # keys of accepted pages for which every model failed (listing answers kept)
    deferred: list[str] = []            # accepted pages whose criteria wait for the next run (only local models left)
    skipped: list[Skipped]              # offers not opened, with the reason
    model_calls: dict[str, int]


def collect_details(collection: CompanyCollection, log: Callable[[str], None] | None = None,
                    **session_options) -> DetailCollection:
    """Detail phase on the new offers kept by the filter, after collect_company().

    log: optional, receives one progress line per page opened, and per failed extraction.
    """
    before = model_calls()
    plan = plan_details(collection.offers, collection.new_keys, [o.key for o in collection.offers if keep(o)],
                        collection.url)
    offers = {o.key: o for o in plan.to_open}
    if log:
        log(f"details: {len(plan.to_open)} pages to open, {len(plan.skipped)} offers not opened")
    pages = open_details(plan.to_open, collection.url, log=log, **session_options)
    details, texts, failed, deferred = [], {}, [], []
    accepted = [page for page in pages if not page.failure]
    for number, page in enumerate(accepted, 1):
        offer = offers[page.key]
        query = OfferInput(company=collection.company, title=offer.title, location=offer.location, ad=page.text)
        # A page cut at DETAIL_MAX_CHARS is not the whole ad
        asked = ask(query, full_ad=not page.truncated, log=log, progress=f"page {number}/{len(accepted)}")
        if asked is None:
            deferred.append(page.key)
            continue
        texts[page.key] = page.text
        if asked.criteria_answers is None:
            failed.append(page.key)
            if log:
                log(f"criteria on the page failed (every model): {page.key}")
            continue
        details.append(DetailAnswers(key=page.key, asked=asked))
    return DetailCollection(company=collection.company, details=details, texts=texts,
                            refused_pages=[p for p in pages if p.failure], failed_extractions=failed,
                            skipped=plan.skipped, model_calls=calls_since(before), deferred=deferred)

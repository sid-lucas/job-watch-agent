"""Collect the offers of one company job list: agent navigation, extraction by the code,
listed_offers table and filter, then the detail phase on the new offers kept.

Offers found are saved even when some chunks failed (the report says so). Offers no longer
listed are not marked here: the judge compares the total announced by the page later.
"""
import sqlite3

from pydantic import BaseModel

from job_watch.list_agent import run as agent_run
from job_watch.list_agent.detail import CheckedDetail, DetailPage, Skipped, extract_detail, open_details, plan_details
from job_watch.list_agent.extraction import CheckedOffer, extract_observations
from job_watch.llm import calls_since, model_calls
from job_watch.offers.listed import now_iso, save_listed_offers
from job_watch.offers.listing_filter import keep


class CompanyCollection(BaseModel):
    company: str
    url: str
    stop: str                       # agent stop reason (not trusted: see the judge)
    pages_reached: int
    offers: list[CheckedOffer]      # every offer of this run, checked and deduplicated
    new_keys: list[str]             # offers seen for the first time
    new_kept: list[CheckedOffer]    # new offers kept by the filter: candidates for the detail phase
    failed_chunks: int
    model_calls: dict[str, int]
    seconds: float


def collect_company(company: str, url: str, conn: sqlite3.Connection) -> CompanyCollection:
    """Run the list agent, extract and check the offers, save them in listed_offers."""
    before = model_calls()
    run = agent_run.run_list_agent(url, company)
    extraction = extract_observations(company, run.observations)
    new_keys = save_listed_offers(conn, company, extraction.offers, now_iso(), keep=keep)
    new = set(new_keys)
    return CompanyCollection(
        company=company, url=url, stop=run.stop, pages_reached=agent_run.pages_reached(run.trail),
        offers=extraction.offers, new_keys=new_keys,
        new_kept=[o for o in extraction.offers if o.key in new and keep(o)],
        failed_chunks=extraction.failed_chunks, model_calls=calls_since(before), seconds=run.seconds,
    )


class DetailCollection(BaseModel):
    company: str
    details: list[CheckedDetail]        # accepted pages, extracted and checked
    texts: dict[str, str]               # offer key -> raw page text (cut), for V2
    refused_pages: list[DetailPage]     # not allowed, redirected, title not found
    failed_extractions: list[str]       # keys of accepted pages for which every model failed
    skipped: list[Skipped]              # offers not opened, with the reason
    model_calls: dict[str, int]


def collect_details(collection: CompanyCollection, **session_options) -> DetailCollection:
    """Detail phase on the new offers kept by the filter, after collect_company()."""
    before = model_calls()
    plan = plan_details(collection.offers, collection.new_keys, [o.key for o in collection.offers if keep(o)],
                        collection.url)
    offers = {o.key: o for o in plan.to_open}
    pages = open_details(plan.to_open, collection.url, **session_options)
    details, texts, failed = [], {}, []
    for page in pages:
        if page.failure:
            continue
        detail = extract_detail(collection.company, offers[page.key], page)
        if detail is None:
            failed.append(page.key)
            continue
        details.append(detail)
        texts[page.key] = page.text
    return DetailCollection(company=collection.company, details=details, texts=texts,
                            refused_pages=[p for p in pages if p.failure], failed_extractions=failed,
                            skipped=plan.skipped, model_calls=calls_since(before))

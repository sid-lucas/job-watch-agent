"""Collect the offers of one company job list: agent navigation, extraction by the code,
listed_offers table and filter.

Offers found are saved even when some chunks failed (the report says so). Offers no longer
listed are not marked here: the judge compares the total announced by the page later.
"""
import sqlite3

from pydantic import BaseModel

from job_watch.list_agent import run as agent_run
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

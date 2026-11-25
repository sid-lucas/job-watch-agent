"""Detail phase, after the list: open the page of each new offer kept by the filter.

This module starts with the choice of the offers to open. Only new offers kept by the
filter, with their own link on the site of the list, up to a budget: every page opened
costs an LLM call and a request to the site, and the phase must stay inside the perimeter
of the agent. Every offer set aside gets a reason, so it can be counted.
"""
from collections import Counter
from typing import Literal

from pydantic import BaseModel

from job_watch import config
from job_watch.list_agent.extraction import CheckedOffer
from job_watch.web.click_rules import site_host

SkipReason = Literal["not_new", "not_kept", "no_link", "other_site", "shared_link", "budget"]


class Skipped(BaseModel):
    key: str
    title: str
    reason: SkipReason


class DetailPlan(BaseModel):
    to_open: list[CheckedOffer]     # in page order
    skipped: list[Skipped]


def plan_details(offers: list[CheckedOffer], new_keys: list[str], kept_keys: list[str], list_url: str,
                 budget: int = config.MAX_DETAIL_PAGES) -> DetailPlan:
    """Offers whose page will be opened, and why the others are not.

    A link shared by several offers is the page of none of them (a generic "Jobs" link):
    all those offers are set aside. The site is checked again here (defense in depth: the
    extraction already empties links to another site), and again by the guard when the page
    is opened.
    """
    new, kept, host = set(new_keys), set(kept_keys), site_host(list_url)
    links = Counter(o.link for o in offers if o.link)
    to_open, skipped = [], []
    for offer in offers:
        if offer.key not in new:
            reason = "not_new"
        elif offer.key not in kept:
            reason = "not_kept"
        elif not offer.link:
            reason = "no_link"
        elif site_host(offer.link) != host:
            reason = "other_site"
        elif links[offer.link] > 1:
            reason = "shared_link"
        elif len(to_open) >= budget:
            reason = "budget"
        else:
            to_open.append(offer)
            continue
        skipped.append(Skipped(key=offer.key, title=offer.title, reason=reason))
    return DetailPlan(to_open=to_open, skipped=skipped)

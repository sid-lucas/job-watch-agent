"""Detail phase, after the list: open the page of each new offer kept by the filter.

This module starts with the choice of the offers to open. Only new offers kept by the
filter, with their own link on the site of the list, up to a budget: every page opened
costs an LLM call and a request to the site, and the phase must stay inside the perimeter
of the agent. Every offer set aside gets a reason, so it can be counted.
"""
import time
from collections import Counter
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from job_watch import config
from job_watch.list_agent.extraction import CheckedOffer, find_in, without_badge
from job_watch.web.click_rules import site_domain
from job_watch.web.session import BrowserSession, SessionError

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
    all those offers are set aside. The registrable domain is checked again here (defense in
    depth: the extraction already empties links to another site), and the browser guard keeps
    the page on the exact host of the offer link when it is opened.
    """
    new, kept, domain = set(new_keys), set(kept_keys), site_domain(list_url)
    links = Counter(o.link for o in offers if o.link)
    to_open, skipped = [], []
    for offer in offers:
        if offer.key not in new:
            reason = "not_new"
        elif offer.key not in kept:
            reason = "not_kept"
        elif not offer.link:
            reason = "no_link"
        elif site_domain(offer.link) != domain:
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


# ---------- opening the pages ----------

PageFailure = Literal["not_allowed", "redirected", "title_not_found"]


class DetailPage(BaseModel):
    key: str
    url: str                        # final URL of the page
    text: str                       # raw page text, cut at DETAIL_MAX_CHARS
    truncated: bool
    failure: PageFailure | None = None      # set: the page is ignored, text is empty
    detail: str = ""


def open_detail(offer: CheckedOffer, list_url: str, **session_options) -> DetailPage:
    """Open the page of one offer (one observation, no click) and accept it only if it shows the title.

    BrowserSession checks robots.txt and the blocked domains before the first request, and its
    guard refuses any navigation to another host. The final URL is checked again.
    """
    try:
        with BrowserSession(offer.link, **session_options) as session:
            obs = session.observe()
    except SessionError as error:
        return DetailPage(key=offer.key, url=offer.link, text="", truncated=False, failure="not_allowed",
                          detail=str(error)[:150])
    if site_domain(obs.url) != site_domain(list_url):
        return DetailPage(key=offer.key, url=obs.url, text="", truncated=False, failure="redirected",
                          detail=f"now on {site_domain(obs.url)}")
    text = obs.new_text_full        # first observation: every line of the page, never cut
    # The title with a label at its end (offers stored before the labels were left out) is accepted too
    if find_in(text, offer.title) is None and find_in(text, without_badge(offer.title)) is None:
        return DetailPage(key=offer.key, url=obs.url, text="", truncated=False, failure="title_not_found",
                          detail=f"{offer.title[:80]!r} not in the page")
    return DetailPage(key=offer.key, url=obs.url, text=text[:config.DETAIL_MAX_CHARS],
                      truncated=len(text) > config.DETAIL_MAX_CHARS)


def open_details(offers: list[CheckedOffer], list_url: str, pause: float = config.DETAIL_PAUSE_SECONDS,
                 sleep: Callable[[float], None] | None = None, log: Callable[[str], None] | None = None,
                 **session_options) -> list[DetailPage]:
    """Open the offer pages one after the other, with a pause between two pages (time.sleep by default).

    log: optional, receives one progress line per page.
    """
    pages = []
    for number, offer in enumerate(offers):
        if number:
            (sleep or time.sleep)(pause)
        page = open_detail(offer, list_url, **session_options)
        pages.append(page)
        if log:
            result = "accepted" if page.failure is None else f"refused: {page.failure} ({page.detail[:60]})"
            log(f"detail {number + 1}/{len(offers)}: {offer.title[:50]!r} {result}")
    return pages

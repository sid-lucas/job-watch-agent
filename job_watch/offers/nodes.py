from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

import feedparser
from bs4 import BeautifulSoup

from job_watch import config
from job_watch.offers.criteria import Verdict
from job_watch.offers.scoring import ask, domain_kept, offer_query, offer_verdict
from job_watch.offers.state import JobState, Offer
from job_watch.offers.triage import TriageInput, triage_offers

from job_watch.offers import storage


def to_iso(rss_date: str) -> str:
    """Convert an RSS date (e.g. 'Sun, 22 Nov 2026 12:56:14 GMT') to ISO 8601."""
    try:
        return parsedate_to_datetime(rss_date).isoformat()
    except (TypeError, ValueError):
        return ""  # missing or malformed date


def parse_title(raw_title: str) -> tuple[str, str]:
    """Split 'Position @ Company [Salary]' into (position, company)."""
    title_part = raw_title.split(" [")[0]          # drop the salary
    if " @ " in title_part:
        position, company = title_part.split(" @ ", 1)
        return position.strip(), company.strip()
    return title_part.strip(), "unknown"


def clean_link(url: str) -> str:
    """Remove query parameters (utm tracking) from a URL."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def html_to_text(html: str) -> str:
    """Convert an HTML description to plain text."""
    return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)


def without_board_salary(description: str) -> str:
    """The description without the first line "Salary: ..." that the feed adds to every offer.

    That line is an estimate of the job board, not the employer's salary: the criteria about the
    salary must only read what the employer writes in the ad.
    """
    first, _, rest = description.partition("\n")
    return rest if first.strip().casefold().startswith("salary:") else description


def wants(state: JobState, source: str) -> bool:
    """True when the run includes this source ("rss" or "career_sites"; both by default)."""
    return source in state.get("sources", ["rss", "career_sites"])


def fetch_rss(state: JobState) -> dict:
    """Node: read the RSS feeds of user_config.py and convert each entry to an Offer (source: the feed name)."""
    if not wants(state, "rss"):
        print("fetch_rss: skipped")
        return {"offers": state.get("offers", [])}
    fetched = datetime.now(timezone.utc).isoformat()
    offers: list[Offer] = []
    for feed in config.SETTINGS.rss_feeds:
        entries = feedparser.parse(feed.url).entries
        for entry in entries:
            position, company = parse_title(entry.title)
            link = clean_link(entry.link)
            offers.append(Offer(
                key=storage.rss_key(link),
                title=position,
                company=company,
                location="unknown",     # the feed gives no location
                description=without_board_salary(html_to_text(entry.get("description", ""))),
                source=feed.name,
                link=link,
                published=to_iso(entry.get("published", "")),
                fetched=fetched,
            ))
        print(f"fetch_rss: {feed.name}: {len(entries)} offers")
    return {"offers": state.get("offers", []) + offers}


def triage_rss(state: JobState) -> dict:
    """Node: triage of the new offers of the feeds whose "triage" flag is set (title, company; the feed
    gives no location), as for career sites. The offers of the other feeds keep no domain: kept."""
    offers = [dict(o) for o in state.get("offers", [])]
    known = storage.known_offers()
    triaged_feeds = {feed.name for feed in config.SETTINGS.rss_feeds if feed.triage}
    todo = [o for o in offers if o["source"] in triaged_feeds and (o["company"], o["key"]) not in known]
    if not todo:
        return {"offers": offers}
    verdicts = triage_offers([TriageInput(title=o["title"], location=o["location"], company=o["company"])
                              for o in todo], log=lambda line: print(f"  {line}", flush=True))
    for offer, verdict in zip(todo, verdicts):
        offer.update(domain=verdict.domain)
    print(f"triage_rss: {len(todo)} new RSS offers triaged")
    return {"offers": offers}


NOT_SCORED = Verdict(status="new", score=0, reasons=["not scored: no answers to the current questions"])


def score_offers(state: JobState) -> dict:
    """Node: the criteria of the user on each offer (offers/scoring.py).

    New RSS offers whose domain is kept are asked now (one LLM call each, on the feed description);
    career-site offers come with their answers (listing or detail page). Known offers are never
    asked again: they are not stored again either.
    """
    known = storage.known_offers()

    def to_ask(offer: dict) -> bool:
        return ((offer["company"], offer["key"]) not in known and offer["source"] != "career_site"
                and "criteria_questions" not in offer and domain_kept(offer.get("domain")))

    total = sum(to_ask(o) for o in state["offers"])
    offers, asked, deferred = [], 0, 0
    for original in state["offers"]:
        offer = dict(original)  # work on a copy, never modify the input state
        if to_ask(offer):
            asked += 1
            answers = ask(offer_query(offer), full_ad=False, progress=f"{asked}/{total}",
                          log=lambda line: print(f"  {line}", flush=True))
            if answers is None:
                deferred += 1           # not stored: still new on the next run
                continue
            offer.update(answers.model_dump())
        verdict = offer_verdict(offer) or NOT_SCORED
        offer.update(status=verdict.status, score=verdict.score, reasons=verdict.reasons)
        offers.append(offer)
    kept = sum(1 for o in offers if o["status"] == "new")
    print(f"score_offers: {asked - deferred} RSS offers asked, {deferred} deferred to the next run, "
          f"{kept} kept, {len(offers) - kept} rejected")
    return {"offers": offers}


def deduplicate(state: JobState) -> dict:
    """Node: remove offers with the same link, or the same company and title.

    An empty link (career-site offer without its own page) never makes two offers equal.
    """
    seen_links: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()

    unique = []
    for offer in state["offers"]:
        key = (offer["company"].lower(), offer["title"].lower())
        if (offer["link"] and offer["link"] in seen_links) or key in seen_keys:
            continue
        if offer["link"]:
            seen_links.add(offer["link"])
        seen_keys.add(key)
        unique.append(offer)

    print(f"deduplicate: {len(unique)} / {len(state['offers'])} offers unique")
    return {"offers": unique}


def save_results(state: JobState) -> dict:
    """Node: store offers in the local database (already known offers are skipped).

    The career-site collections go to listed_offers in the same transaction: an offer is
    marked as seen only once it is stored.
    """
    collections = state.get("collections", [])

    def write_listed(conn) -> None:
        from job_watch.list_agent.collect import save_collection     # career sites only
        for collection in collections:
            save_collection(conn, collection, commit=False)

    new_offers = storage.save_offers(state["offers"], before_commit=write_listed if collections else None)
    print(f"save_results: {len(new_offers)} new offers stored, "
          f"{len(state['offers']) - len(new_offers)} already known"
          + (f", {len(collections)} career-site lists recorded" if collections else ""))
    return {"new_offers": new_offers}
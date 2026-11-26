import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

import feedparser
from bs4 import BeautifulSoup

from job_watch import config
from job_watch.offers.state import JobState, Offer

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


def wants(state: JobState, source: str) -> bool:
    """True when the run includes this source ("rss" or "career_sites"; both by default)."""
    return source in state.get("sources", ["rss", "career_sites"])


def fetch_rss(state: JobState) -> dict:
    """Node: read the RSS feed and convert each entry to an Offer."""
    if not wants(state, "rss"):
        print("fetch_rss: skipped")
        return {"offers": state.get("offers", [])}
    feed = feedparser.parse(config.FEED_URL)
    fetched = datetime.now(timezone.utc).isoformat()

    offers: list[Offer] = []
    for entry in feed.entries:
        position, company = parse_title(entry.title)
        link = clean_link(entry.link)
        offers.append(Offer(
            key=storage.rss_key(link),
            title=position,
            company=company,
            location="unknown", # TODO: CHANGE, the RSS feed has no location
            description=html_to_text(entry.get("description", "")),
            source=config.SOURCE_NAME,
            link=link,
            published=to_iso(entry.get("published", "")),
            fetched=fetched,
        ))

    print(f"fetch_rss: {len(offers)} offers")
    return {"offers": state.get("offers", []) + offers}


def filter_keywords(state: JobState) -> dict:
    """Node: keep only RSS offers that contain at least one keyword (whole words).

    Career-site offers were already kept by the triage and the listing filter: not filtered again.
    """
    patterns = [re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in config.KEYWORDS]

    kept = []
    for offer in state["offers"]:
        text = f"{offer['title']} {offer['description']}"
        if offer["source"] == "career_site" or any(p.search(text) for p in patterns):
            kept.append(offer)

    print(f"filter_keywords: {len(kept)} / {len(state['offers'])} offers kept")
    return {"offers": kept}


def rule_matches(rule: dict, offer: Offer) -> bool:
    """Return True when a rule matches its field of the offer."""
    text = offer[rule["field"]]    
    if "check" in rule:
        return rule["check"](text)
    return re.search(rule["pattern"], text, re.IGNORECASE) is not None


def apply_flags(state: JobState) -> dict:
    """Node: reject offers with red flags, score the others."""
    offers = []
    for original in state["offers"]:
        offer = dict(original)  # work on a copy, never modify the input state

        rejected_by = [r["name"] for r in config.REJECT_RULES if rule_matches(r, offer)]
        if rejected_by:
            offer["status"] = "rejected"
            offer["score"] = 0
            offer["reasons"] = [f"rejected: {name}" for name in rejected_by]
        else:
            matched = [r for r in config.SCORE_RULES if rule_matches(r, offer)]
            offer["status"] = "new"
            offer["score"] = sum(r["points"] for r in matched)
            offer["reasons"] = [f"{r['name']} ({r['points']:+d})" for r in matched]

        offers.append(offer)

    kept = sum(1 for o in offers if o["status"] == "new")
    print(f"apply_flags: {kept} kept, {len(offers) - kept} rejected")
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
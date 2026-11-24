import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import feedparser
from bs4 import BeautifulSoup

import config
from state import JobState, Offer


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


def fetch_rss(state: JobState) -> dict:
    """Node: read the RSS feed and convert each entry to an Offer."""
    feed = feedparser.parse(config.FEED_URL)
    fetched = datetime.now(timezone.utc).isoformat()

    offers: list[Offer] = []
    for entry in feed.entries:
        position, company = parse_title(entry.title)
        offers.append(Offer(
            title=position,
            company=company,
            location="unknown", # TODO: CHANGE, the RSS feed has no location
            description=html_to_text(entry.get("description", "")),
            source=config.SOURCE_NAME,
            link=clean_link(entry.link),
            published=entry.get("published", ""),
            fetched=fetched,
        ))

    print(f"fetch_rss: {len(offers)} offers")
    return {"offers": offers}

def filter_keywords(state: JobState) -> dict:
    """Node: keep only offers that contain at least one keyword (whole words)."""
    patterns = [re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in config.KEYWORDS]

    kept = []
    for offer in state["offers"]:
        text = f"{offer['title']} {offer['description']}"
        if any(p.search(text) for p in patterns):
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
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
            location="unknown",              # the RSS feed has no location (option A)
            description=html_to_text(entry.get("description", "")),
            source=config.SOURCE_NAME,                # use the value from config.py
            link=clean_link(entry.link),
            published=entry.get("published", ""),
            fetched=fetched,
        ))

    print(f"fetch_rss: {len(offers)} offers")
    return {"offers": offers}
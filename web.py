from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

import config


def can_fetch(url: str) -> bool:
    """Return True when the site's robots.txt allows fetching this URL."""
    parts = urlsplit(url)
    robots = RobotFileParser(f"{parts.scheme}://{parts.netloc}/robots.txt")
    try:
        robots.read()
    except Exception:
        return False  # robots.txt unreachable: do not fetch
    return robots.can_fetch(config.USER_AGENT, url)


def fetch_text(url: str) -> str:
    """Fetch a page and return its visible text, truncated. Empty string if not allowed."""
    if not can_fetch(url):
        return ""
    response = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()  # remove non-content parts
    text = soup.get_text(separator="\n", strip=True)
    return text[:config.MAX_PAGE_CHARS]
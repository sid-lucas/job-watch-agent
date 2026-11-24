from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

import config


def can_fetch(url: str) -> bool:
    """Return True when the domain is not blocked and its robots.txt allows this URL."""
    parts = urlsplit(url)
    domain = parts.netloc.lower()
    if any(domain == d or domain.endswith("." + d) for d in config.BLOCKED_DOMAINS):
        return False

    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        response = requests.get(robots_url, headers={"User-Agent": config.USER_AGENT},
                                timeout=config.ROBOTS_TIMEOUT)
    except requests.RequestException:
        return False  # robots.txt unreachable: do not fetch

    robots = RobotFileParser()
    if response.status_code == 404:
        robots.parse([])                         # no robots.txt: everything is allowed
    elif response.ok:
        robots.parse(response.text.splitlines())
    else:
        return False                             # other errors: do not fetch
    return robots.can_fetch(config.USER_AGENT, url)


def fetch_text(url: str) -> str:
    """Fetch a page and return its visible text, truncated. Empty string if not allowed."""
    if not can_fetch(url):
        return ""
    response = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return text[:config.MAX_PAGE_CHARS]
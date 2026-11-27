from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from job_watch import config

ALLOWED, DISALLOWED, ERROR = "allowed", "disallowed", "error"

# robots.txt parsed per site during a run; failed downloads are not cached, so they are retried
_robots_cache: dict[str, RobotFileParser] = {}


def _load_robots(base_url: str) -> RobotFileParser | None:
    """Return the parsed robots.txt of a site, or None if it could not be read."""
    if base_url in _robots_cache:
        return _robots_cache[base_url]
    try:
        response = requests.get(f"{base_url}/robots.txt", headers={"User-Agent": config.USER_AGENT},
                                timeout=config.ROBOTS_TIMEOUT)
    except requests.RequestException:
        return None                              # unreachable: unknown, maybe temporary

    robots = RobotFileParser()
    if response.status_code == 404:
        robots.parse([])                         # no robots.txt: everything is allowed
    elif response.ok:
        robots.parse(response.text.splitlines())
    else:
        return None                              # other errors: unknown, maybe temporary
    _robots_cache[base_url] = robots
    return robots


def robots_status(url: str) -> str:
    """Return ALLOWED, DISALLOWED (blocked domain or robots.txt rule) or ERROR (robots.txt unreadable)."""
    parts = urlsplit(url)
    domain = parts.netloc.lower()
    if any(domain == d or domain.endswith("." + d) for d in config.BLOCKED_DOMAINS):
        return DISALLOWED

    robots = _load_robots(f"{parts.scheme}://{parts.netloc}")
    if robots is None:
        return ERROR
    return ALLOWED if robots.can_fetch(config.USER_AGENT, url) else DISALLOWED


def can_fetch(url: str) -> bool:
    """Return True only when the URL is explicitly allowed. Errors are treated as not allowed."""
    return robots_status(url) == ALLOWED

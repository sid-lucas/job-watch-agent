"""Rules that choose a job list URL among the candidates of a registry entry.

Rules, in order of confidence:
1. a candidate hosted on a known recruiting platform
2. a jobs/careers subdomain whose domain matches the company name
browse() opens the company's own career pages in a headless browser and keeps the links
that match a rule.
"""
import re
import unicodedata
from urllib.parse import urlsplit

from job_watch import config
from job_watch.web.browser import page_links
from job_watch.registry.store import detect_platform

MAX_BROWSED_PAGES = 2   # company pages opened per entry


def normalize(name: str) -> str:
    # "État de Genève" -> "etatdegeneve", "swisspost-cybersecurity" -> "swisspostcybersecurity"
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower())


def shortest_path(candidates: list[dict]) -> dict:
    # The shortest path is usually the job list root, not a single offer
    return min(candidates, key=lambda c: len(urlsplit(c["url"]).path))


def domain_matches(url: str, names: list[str]) -> bool:
    netloc = urlsplit(url).netloc.lower()

    # Domains declared in user_config, for names that do not appear in the domain
    for name in names:
        for domain in config.COMPANY_DOMAINS.get(name, []):
            if netloc == domain or netloc.endswith("." + domain):
                return True

    labels = [normalize(label) for label in netloc.split(".")]
    for name in map(normalize, names):
        if not name:
            continue
        if len(name) < 5:
            # Short names (ITU, Syz) must start a domain label, to avoid matches inside unrelated words
            if any(label.startswith(name) for label in labels):
                return True
        elif any(name in label for label in labels):
            return True
    return False


def is_job_subdomain(url: str) -> bool:
    first_label = urlsplit(url).netloc.lower().split(".")[0]
    return first_label.startswith(("job", "career"))


def resolve(candidates: list[dict], names: list[str]) -> tuple[dict, str] | None:
    on_platform = [c for c in candidates if c["platform"]]
    if on_platform:
        return shortest_path(on_platform), "platform rule"

    on_job_subdomain = [c for c in candidates
                        if is_job_subdomain(c["url"]) and domain_matches(c["url"], names)]
    if on_job_subdomain:
        return shortest_path(on_job_subdomain), "job subdomain rule"

    return None


def browse(entry: dict, names: list[str]) -> list[dict]:
    """Open the company's own career pages and keep the links that match a rule."""
    sources = [c["url"] for c in entry["candidates"] if domain_matches(c["url"], names)]
    discovered, seen = [], set()
    for source in sources[:MAX_BROWSED_PAGES]:
        for link in page_links(source):
            if link in seen:
                continue
            seen.add(link)
            platform = detect_platform(link)
            if platform or (is_job_subdomain(link) and domain_matches(link, names)):
                discovered.append({"url": link, "title": "", "platform": platform})
    return discovered

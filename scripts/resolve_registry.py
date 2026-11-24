"""Choose the job list URL of each registry entry automatically.

Entries with status "to_check" and entries already resolved by a rule are (re)computed.
Entries edited by hand (no "resolved_by") are never changed.
Rules, in order of confidence:
1. a candidate hosted on a known recruiting platform
2. a jobs/careers subdomain whose domain matches the company name
If no search candidate matches, the company's own career pages are opened in a headless
browser and the same rules are applied to their links (cached in "discovered").
A job list found but forbidden by robots.txt gets status "blocked".
"""
import re
from urllib.parse import urlsplit

from job_watch import web
from job_watch.browser import page_links
from job_watch.registry import detect_platform, job_list_root, load_registry, save_registry

MAX_BROWSED_PAGES = 2   # company pages opened per entry


def normalize(name: str) -> str:
    # "Kudelski Security" -> "kudelskisecurity", "Swiss Post" -> "swisspost"
    return re.sub(r"[^a-z0-9]", "", name.lower())


def shortest_path(candidates: list[dict]) -> dict:
    # The shortest path is usually the job list root, not a single offer
    return min(candidates, key=lambda c: len(urlsplit(c["url"]).path))


def domain_matches(url: str, names: list[str]) -> bool:
    labels = urlsplit(url).netloc.lower().split(".")
    for name in map(normalize, names):
        # Exact label for short names (ITU, CERN), substring for longer ones
        if any(label == name or (len(name) >= 5 and name in label) for label in labels):
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


def main():
    registry = load_registry()

    for company, entry in registry.items():
        if entry["status"] != "to_check" and "resolved_by" not in entry:
            continue    # edited by hand
        if "verified" in entry:
            continue    # decided by the page judge (verify_registry)
        names = [company] + entry.get("aliases", [])

        result = resolve(entry["candidates"], names)
        prefix = ""
        if not result:
            if "discovered" not in entry:
                print(f"Browsing {company}...")
                entry["discovered"] = browse(entry, names)
                save_registry(registry)     # browsing is slow: keep the result even if interrupted
            result = resolve(entry["discovered"], names)
            prefix = "browser + "
        if not result:
            continue

        candidate, rule = result
        url = job_list_root(candidate["url"], candidate["platform"])
        if not web.can_fetch(url):
            url = candidate["url"]
        entry["jobs_url"] = url
        entry["platform"] = candidate["platform"]
        entry["status"] = "ok" if web.can_fetch(url) else "blocked"
        entry["resolved_by"] = prefix + rule

    save_registry(registry)

    for status in ("ok", "blocked"):
        companies = [c for c, e in registry.items() if e["status"] == status]
        print(f"\n{status.upper()} ({len(companies)})")
        for company in companies:
            entry = registry[company]
            print(f"  {company:26} {entry.get('resolved_by', 'manual'):30} {entry['jobs_url']}")
    pending = [c for c, e in registry.items() if e["status"] == "to_check"]
    print(f"\nTO_CHECK ({len(pending)}):", ", ".join(pending))


if __name__ == "__main__":
    main()
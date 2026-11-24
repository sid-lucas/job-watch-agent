"""Choose the job list URL of each registry entry automatically.

Only entries with status "to_check" are changed. Rules, in order of confidence:
1. a candidate hosted on a known recruiting platform
2. a jobs/careers subdomain whose domain matches the company name
"""
import re
from urllib.parse import urlsplit

from job_watch.registry import load_registry, save_registry


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


def resolve(company: str, entry: dict) -> tuple[dict, str] | None:
    candidates = entry["candidates"]

    on_platform = [c for c in candidates if c["platform"]]
    if on_platform:
        return shortest_path(on_platform), "platform rule"

    names = [company] + entry.get("aliases", [])
    on_job_subdomain = [c for c in candidates
                        if is_job_subdomain(c["url"]) and domain_matches(c["url"], names)]
    if on_job_subdomain:
        return shortest_path(on_job_subdomain), "job subdomain rule"

    return None


def main():
    registry = load_registry()

    for company, entry in registry.items():
        if entry["status"] != "to_check":
            continue
        result = resolve(company, entry)
        if result:
            candidate, rule = result
            entry["jobs_url"] = candidate["url"]
            entry["platform"] = candidate["platform"]
            entry["status"] = "ok"
            entry["resolved_by"] = rule

    save_registry(registry)

    resolved = [c for c, e in registry.items() if e["status"] == "ok"]
    pending = [c for c, e in registry.items() if e["status"] == "to_check"]
    print(f"{len(resolved)} resolved, {len(pending)} still to check\n")
    for company in resolved:
        entry = registry[company]
        print(f"  OK  {company:26} {entry['resolved_by']:20} {entry['jobs_url']}")
    print("\nStill to check:", ", ".join(pending))


if __name__ == "__main__":
    main()
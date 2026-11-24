"""Choose the job list URL of each registry entry automatically.

Only entries with status "to_check" are changed. Rule: a candidate hosted on a
known recruiting platform is taken as the job list.
"""
from urllib.parse import urlsplit

from job_watch.registry import load_registry, save_registry


def pick_platform_candidate(candidates: list[dict]) -> dict | None:
    on_platform = [c for c in candidates if c["platform"]]
    if not on_platform:
        return None
    # The shortest path is usually the job list root, not a single offer
    return min(on_platform, key=lambda c: len(urlsplit(c["url"]).path))


def main():
    registry = load_registry()

    for company, entry in registry.items():
        if entry["status"] != "to_check":
            continue
        candidate = pick_platform_candidate(entry["candidates"])
        if candidate:
            entry["jobs_url"] = candidate["url"]
            entry["platform"] = candidate["platform"]
            entry["status"] = "ok"
            entry["resolved_by"] = "platform rule"

    save_registry(registry)

    resolved = [c for c, e in registry.items() if e["status"] == "ok"]
    pending = [c for c, e in registry.items() if e["status"] == "to_check"]
    print(f"{len(resolved)} resolved, {len(pending)} still to check\n")
    for company in resolved:
        entry = registry[company]
        print(f"  OK     {company:28} {entry['platform']:16} {entry['jobs_url']}")
    print("\nStill to check:", ", ".join(pending))


if __name__ == "__main__":
    main()
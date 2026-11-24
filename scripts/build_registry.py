"""Build the career sites registry (data/career_sites.json) for the target companies.

Only companies missing from the registry are searched (one Serper credit each).
Existing entries are never overwritten.
"""
from datetime import date

from dotenv import load_dotenv

from job_watch import config, search, web
from job_watch.registry import detect_platform, load_registry, save_registry

QUERY_SUFFIX = "careers jobs Switzerland"


def known_names(registry: dict) -> set[str]:
    names = set()
    for name, entry in registry.items():
        names.add(name.lower())
        names.update(alias.lower() for alias in entry.get("aliases", []))
    return names


def companies_to_search(registry: dict) -> list[str]:
    alias_names = {a.lower() for aliases in config.COMPANY_ALIASES.values() for a in aliases}
    known = known_names(registry)
    missing = []
    for company in config.TOP_COMPANIES + config.GOOD_COMPANIES:
        key = company.lower()
        if key in alias_names or key in known or company in missing:
            continue
        missing.append(company)
    return missing


def new_entry(company: str) -> dict:
    results = search.search_offer(company, QUERY_SUFFIX)
    candidates, blocked = [], 0
    for result in results:
        if web.can_fetch(result["link"]):
            candidates.append({
                "url": result["link"],
                "title": result["title"],
                "platform": detect_platform(result["link"]),
            })
        else:
            blocked += 1
    return {
        "aliases": config.COMPANY_ALIASES.get(company, []),
        "status": "to_check",      # to_check -> ok / blocked / none
        "jobs_url": None,          # job list URL
        "platform": None,
        "candidates": candidates,
        "blocked_results": blocked,
        "searched": date.today().isoformat(),
    }


def main():
    load_dotenv()
    registry = load_registry()
    missing = companies_to_search(registry)

    print(f"{len(registry)} companies in the registry, {len(missing)} to search.")
    if not missing:
        return
    print("To search:", ", ".join(missing))
    if input(f"Use {len(missing)} Serper credits? [y/N] ").strip().lower() != "y":
        return

    for company in missing:
        entry = new_entry(company)
        registry[company] = entry
        save_registry(registry)     # saved after each company: credits already spent are never lost
        print(f"{company}: {len(entry['candidates'])} allowed, {entry['blocked_results']} blocked")

    print(f"Done: {config.REGISTRY_PATH}")


if __name__ == "__main__":
    main()
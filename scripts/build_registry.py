"""Build the career sites registry (data/career_sites.json) for the target companies.

Only companies missing from the registry are searched (one Serper credit each).
Existing entries are never overwritten: they are reviewed and edited by hand.
"""
import json
from datetime import date
from urllib.parse import urlsplit

from dotenv import load_dotenv

from job_watch import config, search, web

QUERY_SUFFIX = "careers jobs Switzerland"

PLATFORMS = {
    "myworkdayjobs.com": "workday",
    "oraclecloud.com": "oracle",
    "oraclecloud.eu": "oracle",
    "smartrecruiters.com": "smartrecruiters",
    "greenhouse.io": "greenhouse",
    "taleo.net": "taleo",
    "umantis.com": "umantis",
    "successfactors.com": "successfactors",
    "successfactors.eu": "successfactors",
}


def detect_platform(url: str) -> str | None:
    domain = urlsplit(url).netloc.lower()
    for suffix, platform in PLATFORMS.items():
        if domain == suffix or domain.endswith("." + suffix):
            return platform
    return None


def load_registry() -> dict:
    if config.REGISTRY_PATH.exists():
        return json.loads(config.REGISTRY_PATH.read_text(encoding="utf-8"))
    return {}


def save_registry(registry: dict) -> None:
    # Write to a temporary file first so an interruption never corrupts the registry
    tmp = config.REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.REGISTRY_PATH)


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
        "status": "to_check",      # to_check -> ok / none after manual review
        "jobs_url": None,          # job list URL, chosen by hand among the candidates
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

    print(f"Done. Review {config.REGISTRY_PATH} and set jobs_url, platform and status for each entry.")


if __name__ == "__main__":
    main()
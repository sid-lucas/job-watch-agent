"""Show the registry: job list URL and status of each company (read only)."""
from job_watch.registry import load_registry

STATUSES = ("ok", "blocked", "not_found", "to_check")


def main():
    registry = load_registry()
    for status in STATUSES:
        companies = sorted(c for c, e in registry.items() if e["status"] == status)
        print(f"\n{status.upper()} ({len(companies)})")
        for company in companies:
            entry = registry[company]
            checked = "judge" if "verified" in entry else "rules only"
            print(f"  {company:26} {checked:11} {entry['jobs_url'] or '-'}")


if __name__ == "__main__":
    main()
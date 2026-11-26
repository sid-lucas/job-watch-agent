"""Add a company to the registry from a known job list URL (no web search, no Serper credits).

Checks robots.txt, then the page judge (one LLM call) must confirm a job list owned by the
company; otherwise nothing is written and the reason is printed.

    python -m scripts.add_registry_entry "COMPANY" URL
"""
import sys

from job_watch.registry.add import check_known_list
from job_watch.registry.store import load_registry, save_registry


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    company, url = sys.argv[1], sys.argv[2]
    registry = load_registry()
    result = check_known_list(company, url, registry)
    if not result.added:
        print(f"REFUSED  {company}: {result.reason}")
        raise SystemExit(1)
    registry[company] = result.entry
    save_registry(registry)
    print(f"ADDED    {company}: {result.entry['jobs_url']}\n         {result.reason}")


if __name__ == "__main__":
    main()

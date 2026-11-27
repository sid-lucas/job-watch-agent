"""Check registry job lists with the LLM page judge.

For each entry not validated yet, URLs are judged in this order, the first job list wins:
1. the URL proposed by the rules (resolve_registry), if any
2. the best candidates on the company's own domain (search and browser links), ranked by
   job-related words in their title and URL (MAX_CANDIDATES)
For each URL, the link proposed by the judge is followed (MAX_HOPS at most), each page being
checked against robots.txt first. Outcomes:
- ok: the judge confirmed a job list
- blocked: the job list is forbidden by robots.txt
- not_found: no job list among the URLs tried (left to the agent); jobs_url is cleared
- retry: a page failed to load or an API was unavailable; retried in a second pass at the end,
  then saved as not_found if it fails again, the cause being kept in the trail
Entries are marked "candidates_judged" once their candidates have been judged.

    python -m scripts.verify_registry                       # entries not validated yet
    python -m scripts.verify_registry --company "Bordier"   # one entry again, even if verified (no Serper)
"""
import argparse
from datetime import date

from job_watch.registry.store import load_registry, save_registry
from job_watch.registry.verify import MAX_CANDIDATES, MAX_HOPS, check_entry, needs_check


def run(registry: dict, companies: list[str], last_pass: bool, force: bool = False) -> list[str]:
    """Check the given companies and return those to retry."""
    to_retry = []
    for company in companies:
        entry = registry[company]
        outcome, url, trail, from_candidates, temporary_failure = check_entry(company, entry, force=force)

        if outcome == "not_found" and temporary_failure and not last_pass:
            print(f"RETRY     {company:26} {trail[-1]['reason']}, retried at the end")
            to_retry.append(company)
            continue

        previous_trail = entry.get("verified", {}).get("trail", [])
        entry["status"] = outcome
        entry["jobs_url"] = url
        entry["verified"] = {"date": date.today().isoformat(), "trail": previous_trail + trail}
        if from_candidates:
            entry["candidates_judged"] = True
            if outcome in ("ok", "blocked"):
                entry["resolved_by"] = "candidate judge"
        save_registry(registry)     # saved after each company: LLM calls already made are never lost

        print(f"{outcome.upper():9} {company:26} {url or '(no job list)'}")
        if len(trail) > 1 or outcome != "ok":
            for step in trail:
                print(f"          {step['page_type']:13} {step['url']}  ({step['reason']})")
    return to_retry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", help="judge this entry again, even if it was verified")
    args = parser.parse_args()
    registry = load_registry()
    if args.company:
        name = next((c for c in registry if c.casefold() == args.company.casefold()), None)
        if name is None:
            raise SystemExit(f"{args.company!r} is not in the registry")
        print(f"{name}: {registry[name].get('jobs_url')} judged again, then up to {MAX_CANDIDATES} candidates "
              f"(1 to {(MAX_CANDIDATES + 1) * (MAX_HOPS + 1)} LLM calls, no Serper).")
        run(registry, [name], last_pass=True, force=True)
        return
    todo = [c for c, e in registry.items() if needs_check(e)]

    print(f"{len(todo)} entries to check (1 to {(MAX_CANDIDATES + 1) * (MAX_HOPS + 1)} LLM calls each).")
    if not todo or input("Continue? [y/N] ").strip().lower() != "y":
        return

    to_retry = run(registry, todo, last_pass=False)
    if to_retry:
        print(f"\nSecond pass on {len(to_retry)} entries to retry")
        run(registry, to_retry, last_pass=True)


if __name__ == "__main__":
    main()
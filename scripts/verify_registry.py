"""Check the job list URL of each "ok" registry entry with the LLM page judge.

If the page is not a job list, the link proposed by the judge is followed (MAX_HOPS at most),
each page being checked against robots.txt first. Outcomes:
- ok: the judge confirmed a job list
- blocked: the next link is forbidden by robots.txt
- not_found: the judge found no job list and no link to follow (left to the agent)
- retry: a page failed to load; nothing is saved, the entry is retried on the next run
Decisions are cached in "verified": entries already verified are skipped.
"""
from datetime import date

from job_watch import web
from job_watch.browser import render_page
from job_watch.page_judge import judge_page
from job_watch.registry import load_registry, save_registry

MAX_HOPS = 2    # links followed after the first page


def verify(company: str, start_url: str) -> tuple[str, str, list[dict]]:
    """Return (outcome, url, trail): outcome is "ok", "blocked", "not_found" or "retry"."""
    url, trail, visited = start_url, [], set()
    for hop in range(MAX_HOPS + 1):
        visited.add(url)
        if not web.can_fetch(url):
            trail.append({"url": url, "page_type": "not fetched", "reason": "forbidden by robots.txt"})
            return "blocked", url, trail
        page = render_page(url)
        if page is None:
            trail.append({"url": url, "page_type": "not fetched", "reason": "page failed to load"})
            return "retry", start_url, trail

        answer = judge_page(company, page)
        trail.append({"url": page["url"], "page_type": answer.page_type, "reason": answer.reason})
        if answer.page_type == "job_list":
            return "ok", page["url"], trail
        if not answer.jobs_link or answer.jobs_link in visited or hop == MAX_HOPS:
            return "not_found", start_url, trail
        url = answer.jobs_link
    return "not_found", start_url, trail


def main():
    registry = load_registry()
    todo = [c for c, e in registry.items() if e["status"] == "ok" and "verified" not in e]

    print(f"{len(todo)} entries to verify (1 to {MAX_HOPS + 1} LLM calls each).")
    if not todo or input("Continue? [y/N] ").strip().lower() != "y":
        return

    for company in todo:
        entry = registry[company]
        outcome, url, trail = verify(company, entry["jobs_url"])

        if outcome == "retry":
            print(f"RETRY     {company:26} {trail[-1]['url']}  (page failed to load, retried on next run)")
            continue

        entry["status"] = outcome
        entry["jobs_url"] = url
        entry["verified"] = {"date": date.today().isoformat(), "trail": trail}
        save_registry(registry)     # saved after each company: LLM calls already made are never lost

        print(f"{outcome.upper():9} {company:26} {url}")
        if len(trail) > 1 or outcome != "ok":
            for step in trail:
                print(f"          {step['page_type']:13} {step['url']}  ({step['reason']})")


if __name__ == "__main__":
    main()
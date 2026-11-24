"""Check the job list URL of each "ok" registry entry with the LLM page judge.

If the page is not a job list, the link proposed by the judge is followed (MAX_HOPS at most),
each page being checked against robots.txt first. Outcomes:
- ok: the judge confirmed a job list
- blocked: the next link is forbidden by robots.txt
- not_found: the judge found no job list and no link to follow (left to the agent);
  the rejected URL is removed from jobs_url and only kept in the trail
- retry: a page failed to load or the LLM was unavailable
Entries to retry are tried again in a second pass at the end; if they fail again, they are
saved as not_found, the cause being kept in the trail.
Decisions are cached in "verified": entries already verified are skipped.
"""
import time
from datetime import date

from langchain_google_genai.chat_models import GoogleAPIError

from job_watch import web
from job_watch.browser import render_page
from job_watch.page_judge import judge_page
from job_watch.registry import load_registry, save_registry

MAX_HOPS = 2            # links followed after the first page
LLM_ATTEMPTS = 3        # attempts per page when the LLM API fails
LLM_WAIT_SECONDS = 10   # wait between two attempts


def judge_with_retry(company: str, page: dict):
    """Call the page judge, waiting and retrying on API errors. Return None if it keeps failing."""
    for attempt in range(1, LLM_ATTEMPTS + 1):
        try:
            return judge_page(company, page)
        except GoogleAPIError as error:
            print(f"          LLM error, attempt {attempt}/{LLM_ATTEMPTS}: {str(error)[:80]}")
            if attempt < LLM_ATTEMPTS:
                time.sleep(LLM_WAIT_SECONDS)
    return None


def verify(company: str, start_url: str) -> tuple[str, str | None, list[dict]]:
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

        answer = judge_with_retry(company, page)
        if answer is None:
            trail.append({"url": page["url"], "page_type": "not judged", "reason": "LLM unavailable"})
            return "retry", start_url, trail
        trail.append({"url": page["url"], "page_type": answer.page_type, "reason": answer.reason})
        if answer.page_type == "job_list":
            return "ok", page["url"], trail
        if not answer.jobs_link or answer.jobs_link in visited or hop == MAX_HOPS:
            return "not_found", None, trail
        url = answer.jobs_link
    return "not_found", None, trail


def run(registry: dict, companies: list[str], last_pass: bool) -> list[str]:
    """Verify the given companies and return those to retry."""
    to_retry = []
    for company in companies:
        entry = registry[company]
        outcome, url, trail = verify(company, entry["jobs_url"])

        if outcome == "retry":
            if not last_pass:
                print(f"RETRY     {company:26} {trail[-1]['reason']}, retried at the end")
                to_retry.append(company)
                continue
            outcome, url = "not_found", None   # failed twice: give up, the cause stays in the trail

        entry["status"] = outcome
        entry["jobs_url"] = url
        entry["verified"] = {"date": date.today().isoformat(), "trail": trail}
        save_registry(registry)     # saved after each company: LLM calls already made are never lost

        print(f"{outcome.upper():9} {company:26} {url or '(no job list)'}")
        if len(trail) > 1 or outcome != "ok":
            for step in trail:
                print(f"          {step['page_type']:13} {step['url']}  ({step['reason']})")
    return to_retry


def main():
    registry = load_registry()
    todo = [c for c, e in registry.items() if e["status"] == "ok" and "verified" not in e]

    print(f"{len(todo)} entries to verify (1 to {MAX_HOPS + 1} LLM calls each).")
    if not todo or input("Continue? [y/N] ").strip().lower() != "y":
        return

    to_retry = run(registry, todo, last_pass=False)
    if to_retry:
        print(f"\nSecond pass on {len(to_retry)} entries to retry")
        run(registry, to_retry, last_pass=True)


if __name__ == "__main__":
    main()
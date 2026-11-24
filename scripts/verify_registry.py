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
"""
import time
from datetime import date

from langchain_google_genai.chat_models import GoogleAPIError

from job_watch import web
from job_watch.browser import render_page
from job_watch.page_judge import judge_page
from job_watch.registry import load_registry, save_registry
from scripts.resolve_registry import domain_matches

MAX_HOPS = 2            # links followed after the first page
MAX_CANDIDATES = 3      # candidates judged when the rule URL is missing or rejected
LLM_ATTEMPTS = 3        # attempts per page when the LLM API fails
LLM_WAIT_SECONDS = 10   # wait between two attempts

STRONG_WORDS = ("job", "offre", "emploi", "poste", "vacanc", "opening", "opportunit", "stellen")
WEAK_WORDS = ("career", "carri", "karriere")


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
    """Check one URL. Return (outcome, url, trail): "ok", "blocked", "not_found" or "retry"."""
    url, trail, visited = start_url, [], set()
    for hop in range(MAX_HOPS + 1):
        visited.add(url)
        access = web.robots_status(url)
        if access == web.ERROR:
            trail.append({"url": url, "page_type": "not fetched", "reason": "robots.txt unreadable"})
            return "retry", None, trail
        if access == web.DISALLOWED:
            trail.append({"url": url, "page_type": "not fetched", "reason": "forbidden by robots.txt"})
            return "blocked", url, trail
        page = render_page(url)
        if page is None:
            trail.append({"url": url, "page_type": "not fetched", "reason": "page failed to load"})
            return "retry", None, trail

        answer = judge_with_retry(company, page)
        if answer is None:
            trail.append({"url": page["url"], "page_type": "not judged", "reason": "LLM unavailable"})
            return "retry", None, trail
        trail.append({"url": page["url"], "page_type": answer.page_type, "reason": answer.reason})
        if answer.page_type == "job_list":
            return "ok", page["url"], trail
        if not answer.jobs_link or answer.jobs_link in visited or hop == MAX_HOPS:
            return "not_found", None, trail
        url = answer.jobs_link
    return "not_found", None, trail


def score(candidate: dict) -> int:
    text = (candidate.get("title", "") + " " + candidate["url"]).lower()
    return 2 * sum(w in text for w in STRONG_WORDS) + sum(w in text for w in WEAK_WORDS)


def ranked_candidates(company: str, entry: dict, exclude: set[str]) -> list[str]:
    """Candidates on the company's own domain, best first, without the excluded URLs."""
    names = [company] + entry.get("aliases", [])
    pool = entry["candidates"] + entry.get("discovered", [])
    ranked = []
    for candidate in sorted(pool, key=score, reverse=True):
        url = candidate["url"]
        if url in exclude or url in ranked or not domain_matches(url, names):
            continue
        ranked.append(url)
    return ranked[:MAX_CANDIDATES]


def needs_check(entry: dict) -> bool:
    rule_url_to_check = entry["status"] == "ok" and "verified" not in entry
    candidates_to_check = entry["status"] in ("to_check", "not_found") and not entry.get("candidates_judged")
    return rule_url_to_check or candidates_to_check


def check_entry(company: str, entry: dict) -> tuple[str, str | None, list[dict], bool, bool]:
    """Return (outcome, url, trail, from_candidates, temporary_failure)."""
    previous = {step["url"] for step in entry.get("verified", {}).get("trail", [])}
    urls = []
    if entry["status"] == "ok" and "verified" not in entry and entry["jobs_url"]:
        urls.append(entry["jobs_url"])
    candidates = ranked_candidates(company, entry, exclude=previous | set(urls))
    urls += candidates

    trail, temporary_failure = [], False
    for url in urls:
        outcome, found_url, steps = verify(company, url)
        trail += steps
        if outcome in ("ok", "blocked"):
            return outcome, found_url, trail, url in candidates, False
        if outcome == "retry":
            temporary_failure = True
    if not urls:
        trail.append({"url": "", "page_type": "not fetched", "reason": "no candidate on the company's domain"})
    return "not_found", None, trail, True, temporary_failure


def run(registry: dict, companies: list[str], last_pass: bool) -> list[str]:
    """Check the given companies and return those to retry."""
    to_retry = []
    for company in companies:
        entry = registry[company]
        outcome, url, trail, from_candidates, temporary_failure = check_entry(company, entry)

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
    registry = load_registry()
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
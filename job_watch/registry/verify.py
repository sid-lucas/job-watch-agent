"""Check registry job lists with the LLM page judge, following the links it proposes."""
from job_watch.web import access as web
from job_watch.web.browser import render_page
from job_watch.judges.page_judge import judge_page_with_retry
from job_watch.registry.rules import domain_matches

MAX_HOPS = 2            # links followed after the first page
MAX_CANDIDATES = 3      # candidates judged when the rule URL is missing or rejected

STRONG_WORDS = ("job", "offre", "emploi", "poste", "vacanc", "opening", "opportunit", "stellen")
WEAK_WORDS = ("career", "carri", "karriere")


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

        answer = judge_page_with_retry(company, page)
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

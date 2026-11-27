"""Add one company to the registry from a job list URL already known (no web search, no Serper).

The URL is written only after the same checks as verify_registry: robots.txt and blocked
domains, then the page judge must answer job_list and owner_matches "yes" (an "unknown" owner is
refused). Otherwise nothing is written and the reason is returned.
"""
from datetime import date

from pydantic import BaseModel

from job_watch import config
from job_watch.judges.page_judge import judge_page_with_retry
from job_watch.registry.store import detect_platform
from job_watch.web import access as web
from job_watch.web.browser import render_page


class AddResult(BaseModel):
    added: bool
    reason: str
    entry: dict | None = None


def check_known_list(company: str, url: str, registry: dict, today: date | None = None) -> AddResult:
    """Check the URL and return the registry entry to write, or why it is refused."""
    existing = next((name for name in registry if name.casefold() == company.casefold()), None)
    if existing is not None:
        return AddResult(added=False, reason=f"{existing!r} is already in the registry "
                                             f"(status {registry[existing].get('status')!r}): nothing changed")
    status = web.robots_status(url)
    if status == web.ERROR:
        return AddResult(added=False, reason="robots.txt unreadable: retry later")
    if status == web.DISALLOWED:
        return AddResult(added=False, reason="forbidden by robots.txt or blocked domain")
    page = render_page(url)
    if page is None:
        return AddResult(added=False, reason="page failed to load")
    if not web.can_fetch(page["url"]):
        return AddResult(added=False, reason=f"redirected to a page that is not allowed: {page['url']}")
    answer = judge_page_with_retry(company, page)
    if answer is None:
        return AddResult(added=False, reason="LLM unavailable (every model failed): retry later")
    step = {"url": page["url"], "page_type": answer.page_type, "owner": answer.owner_matches,
            "reason": answer.reason}
    if answer.page_type != "job_list":
        return AddResult(added=False, reason=f"the page judge says {answer.page_type!r}, not a job list: "
                                             f"{answer.reason}")
    if answer.owner_matches != "yes":
        return AddResult(added=False, reason=f"the page judge cannot confirm the owner ({answer.owner_matches}): "
                                             f"{answer.reason}")
    entry = {
        "aliases": config.SETTINGS.company(company).aliases,
        "status": "ok",
        "jobs_url": page["url"],
        "platform": detect_platform(page["url"]),
        "candidates": [],
        "blocked_results": 0,
        "resolved_by": "known url",
        "candidates_judged": True,
        "verified": {"date": (today or date.today()).isoformat(), "trail": [step]},
    }
    return AddResult(added=True, reason=f"job list confirmed: {answer.reason}", entry=entry)

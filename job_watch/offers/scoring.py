"""The criteria of the user applied to the offers of the pipeline: ask the LLM once, store the raw
answers with the offer, check them and score in code (again at any time, without LLM).

    listing (career sites): domain kept? then the criteria on the listing data; a reject sets the
                            offer aside before its page is opened
    detail page:            the criteria again on the page text (the whole ad): these answers win
    RSS:                    domain kept? then the criteria on the feed description (not known to be
                            the whole ad: absence criteria never count)

An offer whose domain is not kept is never asked (no LLM call). The stored answers carry the
fingerprint of the questions: they are used only while the questions are the same.

When only local models are left for the run (every cloud model skipped: daily quota spent, key
refused), at most config.LOCAL_ONLY_MAX_CRITERIA offers are still asked; the others are deferred:
they are not stored, so they stay new and are asked on the next run.
"""
import time
from collections.abc import Callable
from datetime import date, datetime

from pydantic import BaseModel

from job_watch import config
from job_watch.llm import calls_since, model_calls, only_local_left
from job_watch.offers.ask_criteria import OfferInput, answer_offer, check_offer
from job_watch.offers.criteria import Answer, Verdict, judge
from job_watch.offers.dates import posted_in_text


class Asked(BaseModel):
    """What is stored with an offer after the LLM was asked."""
    criteria_questions: str             # fingerprint of the questions (Settings.questions_id)
    criteria_answers: list[Answer] | None   # raw answers of the LLM (untrusted); None: every model failed
    criteria_model: str                 # model that answered ("" when every model failed)
    full_ad: bool                       # the text was the whole ad (an offer page read)


def domain_kept(domain: str | None) -> bool:
    """No domain (not triaged, or no valid answer): kept, never set aside on what is not known."""
    return domain is None or domain in config.SETTINGS.kept_domains


def domain_rejection(domain: str | None) -> Verdict | None:
    if domain_kept(domain):
        return None
    return Verdict(status="rejected", score=0, reasons=[f"rejected: domain not kept | {domain!r}"])


_local_only = {"asked": 0}     # offers asked during the run while only local models were left


def ask(query: OfferInput, full_ad: bool, log: Callable[[str], None] | None = None,
        progress: str = "") -> Asked | None:
    """One LLM call: the criteria answered for this offer, with the model that answered.

    None: deferred (only local models left, and LOCAL_ONLY_MAX_CRITERIA offers already asked).
    log: optional, receives one line: progress, title, model and duration.
    """
    label = f"criteria{' ' + progress if progress else ''}: {query.title[:60]!r}"
    if only_local_left():
        if _local_only["asked"] >= config.LOCAL_ONLY_MAX_CRITERIA:
            if log:
                log(f"{label} deferred to the next run (only local models left)")
            return None
        _local_only["asked"] += 1
    before, start = model_calls(), time.monotonic()
    _, raw = answer_offer(config.SETTINGS, query, full_ad=full_ad)
    model = next((name for name in calls_since(before) if " " not in name), "") if raw is not None else ""
    if log:
        answered = "every model failed" if raw is None else model or "answered (model not recorded)"
        log(f"{label} {answered}, {time.monotonic() - start:.1f} s")
    return Asked(criteria_questions=config.SETTINGS.questions_id, criteria_answers=raw, criteria_model=model,
                 full_ad=full_ad)


def _day(value: str | None) -> date | None:
    try:
        return datetime.fromisoformat(value).date() if value else None
    except ValueError:
        return None


def posted_date(offer: dict) -> date | None:
    """Publication date: the one of the source (RSS feed), else a relative date of the stored page
    text of a career-site offer, counted back from the day it was fetched."""
    if published := _day(offer.get("published")):
        return published
    fetched = _day(offer.get("fetched"))
    if offer.get("source") == "career_site" and offer.get("description") and fetched:
        return posted_in_text(offer["description"], fetched)
    return None


def verdict(query: OfferInput, asked: Asked | None, domain: str | None, posted: date | None = None,
            today: date | None = None) -> Verdict | None:
    """Verdict from the stored answers, checked again by the code. None when the answers were given
    to other questions (the offer must be asked again to be scored)."""
    rejected = domain_rejection(domain)
    if rejected:
        return rejected
    if asked is None or asked.criteria_questions != config.SETTINGS.questions_id:
        return None
    checked = check_offer(config.SETTINGS, query, asked.full_ad, asked.criteria_answers)
    return judge(config.SETTINGS, checked, query.company, posted, today or date.today())


def screen_listed(offer, company: str, log: Callable[[str], None] | None = None, progress: str = "") -> bool:
    """A new offer of a career-site list (list_agent.extraction.CheckedOffer): domain, then the
    criteria on the listing data. Sets offer.asked and offer.rejected_by (empty: kept for the detail).
    Returns False when the criteria were deferred to the next run (the offer must stay new)."""
    rejected = domain_rejection(offer.domain)
    if rejected:
        offer.rejected_by = rejected.reasons
        return True
    query = OfferInput(company=company, title=offer.title, location=offer.location)
    offer.asked = ask(query, full_ad=False, log=log, progress=progress)
    if offer.asked is None:
        return False
    found = verdict(query, offer.asked, offer.domain)
    offer.rejected_by = found.reasons if found and found.status == "rejected" else []
    return True


# ---------- offers of the pipeline (dicts, as stored) ----------

def offer_query(offer: dict) -> OfferInput:
    return OfferInput(company=offer["company"], title=offer["title"], location=offer.get("location") or "",
                      ad=offer.get("description") or "")


def stored_asked(offer: dict) -> Asked | None:
    if not offer.get("criteria_questions"):
        return None
    return Asked(criteria_questions=offer["criteria_questions"], criteria_answers=offer.get("criteria_answers"),
                 criteria_model=offer.get("criteria_model") or "", full_ad=bool(offer.get("full_ad")))


def full_ad_of(offer: dict) -> bool:
    """Whether the stored description is the whole ad: as stored with the answers, else a career-site
    page text (an RSS description is not known to be the whole ad)."""
    if offer.get("criteria_questions"):
        return bool(offer.get("full_ad"))
    return offer.get("source") == "career_site" and bool(offer.get("description"))


def offer_verdict(offer: dict, today: date | None = None) -> Verdict | None:
    return verdict(offer_query(offer), stored_asked(offer), offer.get("domain"), posted_date(offer), today)

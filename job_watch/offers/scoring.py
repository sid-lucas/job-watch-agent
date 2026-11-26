"""The criteria of the user applied to the offers of the pipeline: ask the LLM once, store the raw
answers with the offer, check them and score in code (again at any time, without LLM).

    listing (career sites): domain kept? then the criteria on the listing data; a reject sets the
                            offer aside before its page is opened
    detail page:            the criteria again on the page text (the whole ad): these answers win
    RSS:                    domain kept? then the criteria on the feed description (not known to be
                            the whole ad: absence criteria never count)

An offer whose domain is not kept is never asked (no LLM call). The stored answers carry the
fingerprint of the questions: they are used only while the questions are the same.
"""
from datetime import date, datetime

from pydantic import BaseModel

from job_watch import config
from job_watch.llm import calls_since, model_calls
from job_watch.offers.ask_criteria import OfferInput, answer_offer, check_offer
from job_watch.offers.criteria import Answer, Verdict, judge


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


def ask(query: OfferInput, full_ad: bool) -> Asked:
    """One LLM call: the criteria answered for this offer, with the model that answered."""
    before = model_calls()
    _, raw = answer_offer(config.SETTINGS, query, full_ad=full_ad)
    model = next((name for name in calls_since(before) if " " not in name), "") if raw is not None else ""
    return Asked(criteria_questions=config.SETTINGS.questions_id, criteria_answers=raw, criteria_model=model,
                 full_ad=full_ad)


def posted_date(offer: dict) -> date | None:
    try:
        return datetime.fromisoformat(offer["published"]).date() if offer.get("published") else None
    except ValueError:
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


def screen_listed(offer, company: str) -> None:
    """A new offer of a career-site list (list_agent.extraction.CheckedOffer): domain, then the
    criteria on the listing data. Sets offer.asked and offer.rejected_by (empty: kept for the detail)."""
    rejected = domain_rejection(offer.domain)
    if rejected:
        offer.rejected_by = rejected.reasons
        return
    query = OfferInput(company=company, title=offer.title, location=offer.location)
    offer.asked = ask(query, full_ad=False)
    found = verdict(query, offer.asked, offer.domain)
    offer.rejected_by = found.reasons if found and found.status == "rejected" else []


# ---------- offers of the pipeline (dicts, as stored) ----------

def offer_query(offer: dict) -> OfferInput:
    return OfferInput(company=offer["company"], title=offer["title"], location=offer.get("location") or "",
                      ad=offer.get("description") or "")


def stored_asked(offer: dict) -> Asked | None:
    if not offer.get("criteria_questions"):
        return None
    return Asked(criteria_questions=offer["criteria_questions"], criteria_answers=offer.get("criteria_answers"),
                 criteria_model=offer.get("criteria_model") or "", full_ad=bool(offer.get("full_ad")))


def offer_verdict(offer: dict, today: date | None = None) -> Verdict | None:
    return verdict(offer_query(offer), stored_asked(offer), offer.get("domain"), posted_date(offer), today)

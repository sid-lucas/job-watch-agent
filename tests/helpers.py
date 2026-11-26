"""Builders shared by tests (no LLM, no browser)."""
from job_watch.list_agent.detail import CheckedDetail, OfferDetail


def offer_detail(**fields) -> OfferDetail:
    """An LLM fact sheet with every fact unknown, except the given ones."""
    base = dict(summary="Role.", requirements=[], category=None, city="unknown", country="unknown",
                seniority="unknown", experience_years=None, experience_requirement="unknown", languages=[],
                contract="unknown", workload="", salary="", education="unknown", ad_language="en", posted="")
    return OfferDetail(**{**base, **fields})


def checked_detail(key: str, **fields) -> CheckedDetail:
    """A checked fact sheet with every fact unknown, except the given ones."""
    base = dict(key=key, summary="Role.", requirements=[], category=None, city="unknown", country="unknown",
                seniority="unknown", experience_years=None, experience_requirement="unknown", languages=[],
                contract="unknown", contract_doubtful=False, workload="", salary="", education="unknown",
                ad_language="en", posted="", dropped_requirements=0)
    return CheckedDetail(**{**base, **fields})

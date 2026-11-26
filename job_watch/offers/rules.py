"""Rules engine: the user's dealbreakers and bonuses, applied by code to the facts of an offer.

The LLM states facts (triage, detail fact sheet: closed lists, checked against the page); it never
sees these rules and never gives a score. A rule tests one fact with one operator:

    {"name": "senior level", "fact": "seniority", "in": ["senior", "lead"]}            # dealbreaker
    {"name": "security job", "fact": "category", "in": [...], "points": 30}          # bonus

A rule never applies to an unknown fact (None, "", "unknown", empty list): an offer is never
rejected, nor given points, on what is not known. Dealbreakers run as soon as their facts are
known (after the triage on the listing facts, then again on the full facts after the detail).
The score is the sum of the bonuses that apply, each one shown with its points.
"""
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from job_watch import config
from job_watch.offers.checks import is_german_ad
from job_watch.offers.listing_filter import location_verdict

# Facts a rule can test, and what they hold
FACTS = {
    "domain": "triage domain (offers.triage.DOMAINS)",
    "category": "kind of IT job (offers.triage.TECH_CATEGORIES), Technology/IT only",
    "secondary_category": "second kind of IT job",
    "title": "title as written in the list",
    "company": "company name",
    "source": "rss source name, or career_site",
    "location": "switzerland, abroad or unknown (from city and country, else the listed location)",
    "city": "city as written in the offer page",
    "country": "country as written in the offer page",
    "seniority": "graduate, junior, mid, senior or lead (offer page, else words of the title)",
    "experience_years": "years of experience asked (number)",
    "experience_years_required": "years of experience, only when stated as required (number)",
    "languages_required": "languages required (en, fr, de, it, other)",
    "languages_nice": "languages that are a plus",
    "contract": "permanent, fixed_term, internship or apprenticeship",
    "workload": "workload as written (e.g. 80-100 %)",
    "salary": "salary as written, if shown",
    "education": "CFC, ES or HES-university",
    "ad_language": "language the ad is written in (en, fr, de, it, other)",
    "min_years": "minimum years of experience asked (lower bound of a range, number)",
    "salary_min": "lower bound of the salary stated by the employer, yearly CHF (number)",
    "employer_type": "direct, or consulting_delegation (placement at a client)",
    "workload_max": "maximum workload percentage (number, e.g. 100 for 80-100 %)",
    "posted_days_ago": "days since publication (number)",
    "contact_name": "name of a recruiter or hiring manager named in the ad",
}
OPERATORS = ("is", "in", "not_in", "contains", "above", "below", "gte", "gt", "lt", "exists", "matches",
             "in_names")
UNKNOWN = (None, "", "unknown")

# Seniority read from words, for the title (the detail fact sheet checks its answer with the same words)
SENIORITY_WORDS = {
    "lead": r"lead|principal|head of|team ?lead|chef d'équipe|teamleiter\w*|leiter\w*|responsabile",
    "senior": r"senior|sénior|sr\.?",
    "mid": r"mid-level|mid level|intermediate|confirmée?",
    "junior": r"junior|jr\.?",
    "graduate": r"graduate|entry[- ]level|jeune diplômée?|young professional|berufseinsteiger\w*|neolaureat\w*|"
                r"débutante?",
}
SENIORITY_PATTERNS = {level: re.compile(rf"(?<![\w-])(?:{words})(?![\w-])", re.IGNORECASE)
                      for level, words in SENIORITY_WORDS.items()}


def seniority_in(text: str) -> str:
    """Level whose words appear in the text, the highest first; "unknown" when none."""
    return next((level for level, pattern in SENIORITY_PATTERNS.items() if pattern.search(text or "")), "unknown")


class Rule(BaseModel):
    """One rule: a fact, exactly one operator with its value, and points for a bonus."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    fact: str
    points: int | None = None
    is_: Any = Field(default=None, alias="is")
    in_: list | None = Field(default=None, alias="in")
    not_in: list | None = None
    contains: Any = None
    above: float | None = None
    below: float | None = None
    gte: float | None = None
    gt: float | None = None
    lt: float | None = None
    exists: Literal[True] | None = None     # only True: an unknown fact never applies, so False would never match
    matches: str | None = None
    in_names: list[str] | None = None

    @model_validator(mode="after")
    def check(self):
        if self.fact not in FACTS:
            raise ValueError(f"rule {self.name!r}: unknown fact {self.fact!r} (known: {', '.join(FACTS)})")
        given = [op for op in OPERATORS if getattr(self, op if op not in ("is", "in") else op + "_") is not None]
        if len(given) != 1:
            raise ValueError(f"rule {self.name!r}: exactly one operator among {', '.join(OPERATORS)}")
        if self.matches is not None:
            try:
                re.compile(self.matches)
            except re.error as error:
                raise ValueError(f"rule {self.name!r}: invalid regular expression ({error})") from error
        return self

    @property
    def operator(self) -> str:
        return next(op for op in OPERATORS if getattr(self, op if op not in ("is", "in") else op + "_") is not None)

    @property
    def value(self) -> Any:
        op = self.operator
        return getattr(self, op if op not in ("is", "in") else op + "_")


def _fold(value: Any) -> Any:
    return value.casefold() if isinstance(value, str) else value


def known(value: Any) -> bool:
    return not (value in UNKNOWN or value == [])


def applies(rule: Rule, facts: dict) -> bool:
    """True when the fact is known and the rule's test holds."""
    value = facts.get(rule.fact)
    if not known(value):
        return False
    op, expected = rule.operator, rule.value
    if op == "is":
        return _fold(value) == _fold(expected)
    if op == "in":
        return _fold(value) in {_fold(v) for v in expected}
    if op == "not_in":
        return _fold(value) not in {_fold(v) for v in expected}
    if op == "contains":
        return isinstance(value, list) and _fold(expected) in {_fold(v) for v in value}
    if op in ("above", "below", "gte", "gt", "lt"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if op == "gte":
            return value >= expected
        return value > expected if op in ("above", "gt") else value < expected
    if op == "exists":
        return True                 # the fact is known (checked above)
    if op == "matches":
        return re.search(expected, str(value), re.IGNORECASE) is not None
    if op == "in_names":
        return any(name.strip() and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", str(value), re.IGNORECASE)
                   for name in expected)
    return False


def _describe(rule: Rule, facts: dict) -> str:
    return f"{rule.name} ({rule.fact}={facts.get(rule.fact)!r})"


def dealbreakers() -> list[Rule]:
    """The kept domains (config.KEPT_DOMAINS) as a rule, then the user's dealbreakers."""
    rules = [{"name": "domain not kept", "fact": "domain", "not_in": list(config.KEPT_DOMAINS)},
             *config.DEALBREAKERS]
    return [Rule(**rule) for rule in rules]


def bonuses() -> list[Rule]:
    rules = [Rule(**rule) for rule in config.BONUSES]
    missing = [r.name for r in rules if r.points is None]
    if missing:
        raise ValueError(f"bonus rules without points: {', '.join(missing)}")
    return rules


class Verdict(BaseModel):
    status: str             # "new" (kept) or "rejected"
    score: int
    reasons: list[str]      # dealbreakers that rejected the offer, or the bonuses with their points


def rejections(facts: dict) -> list[str]:
    """Dealbreakers that apply to these facts (unknown facts never reject)."""
    return [f"rejected: {_describe(rule, facts)}" for rule in dealbreakers() if applies(rule, facts)]


def judge(facts: dict) -> Verdict:
    """Dealbreakers first; a kept offer gets the sum of its bonuses, each one shown."""
    rejected = rejections(facts)
    if rejected:
        return Verdict(status="rejected", score=0, reasons=rejected)
    matched = [rule for rule in bonuses() if applies(rule, facts)]
    return Verdict(status="new", score=sum(rule.points for rule in matched),
                   reasons=[f"{rule.name} ({rule.points:+d})" for rule in matched])


# ---------- facts of an offer ----------

def _list(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def facts_of(offer: dict) -> dict:
    """Facts of a V1 offer dict (RSS or career site, with the detail fields when known)."""
    city, country = offer.get("city") or "unknown", offer.get("country") or "unknown"
    place = ", ".join(v for v in (city, country) if v != "unknown")
    location = location_verdict(place) if place else "unknown"
    if location == "unknown":
        location = location_verdict(offer.get("location") or "")
    seniority = offer.get("seniority") or "unknown"
    if seniority == "unknown":
        seniority = seniority_in(offer.get("title", ""))
    languages = [n for n in _list(offer.get("languages")) if isinstance(n, dict)]
    years = offer.get("experience_years")
    ad_language = offer.get("ad_language") or "unknown"
    if ad_language == "unknown" and offer.get("description") and is_german_ad(offer["description"]):
        ad_language = "de"
    return {
        "domain": offer.get("domain"),
        "category": offer.get("category"),
        "secondary_category": offer.get("secondary_category"),
        "title": offer.get("title", ""),
        "company": offer.get("company", ""),
        "source": offer.get("source", ""),
        "location": location,
        "city": city,
        "country": country,
        "seniority": seniority,
        "experience_years": years,
        "experience_years_required": years if offer.get("experience_requirement") == "required" else None,
        "languages_required": [n["language"] for n in languages if n.get("level") == "required"],
        "languages_nice": [n["language"] for n in languages if n.get("level") == "nice_to_have"],
        "contract": offer.get("contract") or "unknown",
        "workload": offer.get("workload") or "",
        "salary": offer.get("salary") or "",
        "education": offer.get("education") or "unknown",
        "ad_language": ad_language,
        "min_years": years,
        # Not extracted yet: unknown, so no rule applies to them
        "salary_min": None,
        "employer_type": None,
        "workload_max": None,
        "posted_days_ago": None,
        "contact_name": None,
    }


# ---------- listed offers (career sites), before the detail ----------

def listing_rejections(offer, company: str) -> list[str]:
    """Dealbreakers on the facts known from the list (triage domain, listed location, title)."""
    return rejections(facts_of({"title": offer.title, "company": company, "location": offer.location,
                                "domain": offer.domain, "category": offer.category,
                                "secondary_category": offer.secondary_category, "source": "career_site"}))


def kept(offer) -> bool:
    """A listed offer is kept unless a dealbreaker rejected it (offers not checked yet are kept)."""
    return not offer.rejected_by

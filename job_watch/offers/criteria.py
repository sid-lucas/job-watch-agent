"""Criteria of the user (user_config.py): plain questions answered by the LLM, and generic checks done by code.

    {"ask": "Is the job located outside Switzerland?", "reject": True}
    {"ask": "Is the job in Geneva?", "points": 15, "group": "location"}
    {"type": "company_in", "names": [...], "points": 20, "group": "company"}

Each criterion either rejects the offer ("reject": True) or gives points ("points": N). Criteria
sharing a "group" are exclusive: only the best "yes" of the group counts. "absence": True marks a
question answered by the absence of something in the ad (no quote can prove it).

This module validates the settings when the program starts, with messages that name the criterion.
It also scores one offer: the answers of the LLM (yes / no / unknown, with a quote of the ad) are
checked in code (a "yes" needs its quote in the text), then any reject criterion answered yes
rejects the offer; otherwise the score is the sum of the points of the "yes" criteria, the best one
per group. Unknown never rejects and never gives points.
"""
import hashlib
import re
import unicodedata
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator, model_validator

MAX_PROFILE_CHARS = 1000    # a short context for the LLM, never a CV
MAX_LABEL_CHARS = 50        # name of a criterion in the reasons shown
MAX_EVIDENCE_CHARS = 150    # quote shown in a reason

# Domains of the triage (offers/triage.py), a closed list with what the LLM is told about each one.
# General, never the user's preferences: KEPT_DOMAINS in user_config.py chooses among them.

# Domains (closed list) with what the LLM is told about each one
DOMAINS = {
    "Technology/IT": "software, IT infrastructure, cloud, network, cybersecurity, data, AI, IT support "
                "(developer, sysadmin, SOC analyst, data engineer, IT project manager)",
    "Engineering & R&D (non-IT)": "engineering and technicians outside IT: mechanical, electrical, "
                                  "microtechnology, chemistry, research labs, quality engineering, maintenance",
    "Finance, banking & accounting": "banking, investment, wealth management, accounting, audit, controlling, "
                                     "non-IT risk and compliance",
    "Sales, marketing & communication": "sales, client advisors in shops, marketing, communication, events, "
                                        "public relations",
    "HR, legal & administration": "human resources, legal, administration, assistants, procurement, facilities",
    "Operations, production & logistics": "production, watchmaking, manufacturing, logistics, supply chain, "
                                          "warehouse, operations, catering",
    "Healthcare & humanitarian": "medical and health roles, humanitarian delegates and field roles",
    "Security & safety (physical)": "guards, physical security, safety at work, building security, fire safety",
    "Education & training": "teachers, trainers, apprentices' coaches, academic positions",
    "Other": "the title gives no clue at all",
}


class _Effect(BaseModel):
    """What a "yes" does: reject the offer, or give points (within a group, if any)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reject: Literal[True] | None = None
    points: int | None = None
    group: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def one_effect(self):
        if (self.reject is None) == (self.points is None):
            raise ValueError('give either "reject": True or "points": N (exactly one of them)')
        if self.points == 0:
            raise ValueError('"points" must not be 0')
        if self.reject and self.group is not None:
            raise ValueError('"group" only applies to criteria with "points"')
        return self


class Criterion(_Effect):
    """A question answered by the LLM with yes / no / unknown and a quote of the ad."""
    ask: str = Field(min_length=1)
    label: str | None = Field(default=None, min_length=1, max_length=MAX_LABEL_CHARS)   # shown instead of the question
    absence: bool = False       # "yes" accepted without a quote, only when the full ad was read

    @property
    def short(self) -> str:
        """Name shown with a reason: the label, else the question cut."""
        if self.label:
            return self.label
        if len(self.ask) <= MAX_LABEL_CHARS:
            return self.ask
        return self.ask[:MAX_LABEL_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"      # cut between words

    @model_validator(mode="after")
    def absence_gives_points(self):
        if self.absence and self.reject:
            raise ValueError('"absence" only applies to criteria with "points" (an absence never rejects)')
        return self


class CompanyIn(_Effect):
    """The company of the offer is one of these names (whole names, case-insensitive)."""
    type: Literal["company_in"]
    names: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)


class PostedOlderThan(_Effect):
    """The offer was published more than this number of days ago."""
    type: Literal["posted_older_than_days"]
    days: int = Field(gt=0)


CodeCriterion = Annotated[CompanyIn | PostedOlderThan, Field(discriminator="type")]


class RssFeed(BaseModel):
    """One RSS feed of job offers. triage: the domain triage runs on its new offers (False for a feed
    that only lists jobs of the kept domains, e.g. an IT job board: the criteria decide alone)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1)         # stored as the source of its offers
    url: str = Field(pattern=r"^https?://\S+$")
    triage: bool


class Settings(BaseModel):
    """PROFILE, CRITERIA, CODE_CRITERIA and KEPT_DOMAINS of user_config.py, validated together."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    profile: str = Field(min_length=1, max_length=MAX_PROFILE_CHARS)
    criteria: list[Criterion] = Field(min_length=1)
    code_criteria: list[CodeCriterion] = []
    kept_domains: list[str] = Field(min_length=1)
    rss_feeds: list[RssFeed] = []

    @field_validator("rss_feeds")
    @classmethod
    def distinct_feed_names(cls, feeds: list[RssFeed]) -> list[RssFeed]:
        names = [f.name.casefold() for f in feeds]
        if len(set(names)) != len(names):
            raise ValueError("two feeds have the same name")
        if "career_site" in names:
            raise ValueError('"career_site" is the source name of career-site offers')
        return feeds

    @field_validator("kept_domains")
    @classmethod
    def known_domains(cls, domains: list[str]) -> list[str]:
        unknown = [d for d in domains if d not in DOMAINS]
        if unknown:
            raise ValueError(f"unknown domains {unknown} (known: {', '.join(DOMAINS)})")
        return list(dict.fromkeys(domains))

    @property
    def questions_id(self) -> str:
        """Short fingerprint of the questions: stored answers are reused only for the same questions."""
        return hashlib.sha256("\n".join(c.ask for c in self.criteria).encode()).hexdigest()[:12]

    @field_validator("criteria")
    @classmethod
    def distinct_questions(cls, criteria: list[Criterion]) -> list[Criterion]:
        asks = [c.ask.strip().casefold() for c in criteria]
        repeated = sorted({c.ask.strip() for c in criteria if asks.count(c.ask.strip().casefold()) > 1})
        if repeated:
            raise ValueError(f"the same question is asked twice: {repeated}")
        return criteria


_NAMES = {"profile": "PROFILE", "criteria": "CRITERIA", "code_criteria": "CODE_CRITERIA", "kept_domains": "KEPT_DOMAINS",
          "rss_feeds": "RSS_FEEDS"}


def _where(location: tuple, raw: dict) -> str:
    """'CRITERIA[3] ("Is it an internship?")' for an error location such as ('criteria', 3, 'points')."""
    if not location:
        return "user_config.py"
    name = _NAMES.get(location[0], str(location[0]))
    if len(location) < 2 or not isinstance(location[1], int):
        return name
    index = location[1]
    try:
        item = raw[location[0]][index]
    except (IndexError, KeyError, TypeError):
        item = None
    label = item.get("ask") or item.get("type") or item.get("name") if isinstance(item, dict) else None
    return f"{name}[{index}]" + (f" ({str(label)[:60]!r})" if label else "")


def load_settings(profile, criteria, code_criteria, kept_domains, rss_feeds=()) -> Settings:
    """Validate the settings; raise SystemExit with one clear line per problem."""
    raw = {"profile": profile, "criteria": criteria, "code_criteria": code_criteria, "kept_domains": kept_domains,
           "rss_feeds": list(rss_feeds) if isinstance(rss_feeds, (list, tuple)) else rss_feeds}
    try:
        return TypeAdapter(Settings).validate_python(raw)
    except ValidationError as error:
        lines = []
        for problem in error.errors():
            location = problem["loc"]
            # The union of code criteria adds the "type" tag to the location: not useful to the user
            field = [str(part) for part in location[2:] if part not in ("company_in", "posted_older_than_days")]
            message = problem["msg"].removeprefix("Value error, ")
            kind = problem["type"]
            if kind == "extra_forbidden":
                message = "unknown key (typo?)"
            elif kind == "missing":
                message = "missing key"
            elif kind in ("union_tag_invalid", "union_tag_not_found"):
                message = 'missing or unknown "type" (known: company_in, posted_older_than_days)'
            lines.append(f"- {_where(location, raw)}{' ' + '.'.join(field) if field else ''}: {message}")
        raise SystemExit("Invalid user_config.py:\n" + "\n".join(lines)) from None


# ---------- score of one offer, from the answers of the LLM (checked here) and the code criteria ----------

AnswerValue = Literal["yes", "no", "unknown"]
MIN_QUOTE_CHARS = 3         # shorter quotes ("a", "IT") would be found in almost any text
MAX_QUOTE_CHARS = 300       # a quote is a short piece of evidence, not a copy of the ad


class Answer(BaseModel):
    """One answer of the LLM, as received (untrusted): checked by check_answers()."""
    id: str                 # "c1", "c2"... in the order of CRITERIA
    answer: AnswerValue
    quote: str = ""


class CheckedAnswer(BaseModel):
    """The answer to one criterion after the checks of the code."""
    ask: str
    answer: AnswerValue     # "yes" only with a quote found in the text (or a valid absence)
    quote: str              # the quote of the LLM, kept even when it was not found (to inspect)
    quote_found: bool


class Verdict(BaseModel):
    status: Literal["new", "rejected"]  # "new": kept
    score: int
    reasons: list[str]      # criteria that counted, with points and evidence; or "rejected: <criterion> | <evidence>"


def criterion_id(index: int) -> str:
    return f"c{index + 1}"


def _normal(text: str) -> str:
    """Text compared for quotes: Unicode compatibility form, case folded, whitespace collapsed."""
    return " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())


def quote_in(quote: str, text: str) -> bool:
    """True when the quote appears in the text (case and whitespace ignored), within the size limits."""
    quote = _normal(quote)
    return MIN_QUOTE_CHARS <= len(quote) <= MAX_QUOTE_CHARS and quote in _normal(text)


def check_answers(settings: Settings, answers: list[Answer], text: str, detail_read: bool) -> list[CheckedAnswer]:
    """One checked answer per criterion, in the order of CRITERIA.

    Unknown ids are ignored, the first answer per id wins, a criterion without answer is unknown.
    A "yes" needs a quote found in the text, else it becomes unknown. An "absence" criterion is a
    "yes" without quote only when the full ad was read (detail_read: the page was opened and not
    truncated); a quote it gives must be found too.
    """
    by_id: dict[str, Answer] = {}
    for answer in answers:
        by_id.setdefault(answer.id, answer)
    checked = []
    for index, criterion in enumerate(settings.criteria):
        raw = by_id.get(criterion_id(index))
        value, quote = (raw.answer, raw.quote.strip()) if raw else ("unknown", "")
        found = bool(quote) and quote_in(quote, text)
        if value == "yes":
            if criterion.absence:
                valid = detail_read and (found or not quote)
            else:
                valid = found
            if not valid:
                value = "unknown"
        checked.append(CheckedAnswer(ask=criterion.ask, answer=value, quote=quote[:MAX_QUOTE_CHARS],
                                     quote_found=found))
    return checked


def names_in(text: str, names: list[str]) -> str | None:
    """First name found as a whole name in the text (case-insensitive), or None."""
    return next((name for name in names
                 if name.strip() and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text or "", re.IGNORECASE)),
                None)


class _Match(BaseModel):
    """A criterion whose "yes" holds, with what is shown to the user."""
    label: str
    evidence: str
    reject: bool
    points: int
    group: str | None
    absence: bool = False


def _code_matches(settings: Settings, company: str, posted: date | None, today: date) -> list[_Match]:
    matches = []
    for criterion in settings.code_criteria:
        if isinstance(criterion, CompanyIn):
            name = names_in(company, criterion.names)
            label, evidence = "company in list", name
        else:
            older = posted is not None and (today - posted).days > criterion.days
            label = f"posted over {criterion.days} days ago"
            evidence = posted.isoformat() if older else None
        if evidence:
            matches.append(_Match(label=label, evidence=evidence, reject=bool(criterion.reject),
                                  points=criterion.points or 0, group=criterion.group))
    return matches


def _cut(quote: str) -> str:
    quote = " ".join(quote.split())
    return quote if len(quote) <= MAX_EVIDENCE_CHARS else quote[:MAX_EVIDENCE_CHARS - 1].rstrip() + "…"


def judge(settings: Settings, checked: list[CheckedAnswer], company: str, posted: date | None,
          today: date) -> Verdict:
    """Any reject criterion answered yes rejects the offer. Otherwise score = sum of the points of the
    "yes" criteria, only the best one per group. An absence is contradicted (and dropped) by another
    "yes" of its group: "no experience asked" cannot hold next to "exactly 3 years asked"."""
    matches = [_Match(label=c.short, evidence=_cut(answer.quote) or "absent from the ad", reject=bool(c.reject),
                      points=c.points or 0, group=c.group, absence=c.absence)
               for c, answer in zip(settings.criteria, checked) if answer.answer == "yes"]
    matches += _code_matches(settings, company, posted, today)
    rejected = [m for m in matches if m.reject]
    if rejected:
        return Verdict(status="rejected", score=0,
                       reasons=[f"rejected: {m.label} | {m.evidence!r}" for m in rejected])
    counted = [m for m in matches if m.group is None]
    for group in dict.fromkeys(m.group for m in matches if m.group is not None):
        members = [m for m in matches if m.group == group]
        if any(not m.absence for m in members):
            members = [m for m in members if not m.absence]
        counted.append(max(members, key=lambda m: m.points))
    counted.sort(key=matches.index)         # in the order of the settings
    return Verdict(status="new", score=sum(m.points for m in counted),
                   reasons=[f"{m.label} ({m.points:+d}): {m.evidence!r}" for m in counted])

"""Criteria of the user (user_config.py): plain questions answered by the LLM, and generic checks done by code.

    {"ask": "Is the job located outside Switzerland?", "reject": True}
    {"ask": "Is the job in Geneva?", "points": 15, "group": "location"}
    {"type": "company_in", "names": [...], "points": 20, "group": "company"}

Each criterion either rejects the offer ("reject": True) or gives points ("points": N). Criteria
sharing a "group" are exclusive: only the best "yes" of the group counts. "absence": True marks a
question answered by the absence of something in the ad (no quote can prove it).

This module validates the settings when the program starts, with messages that name the criterion.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator, model_validator

MAX_PROFILE_CHARS = 1000    # a short context for the LLM, never a CV


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
    absence: bool = False       # "yes" accepted without a quote, only when the full ad was read

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


class Settings(BaseModel):
    """PROFILE, CRITERIA and CODE_CRITERIA of user_config.py, validated together."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    profile: str = Field(min_length=1, max_length=MAX_PROFILE_CHARS)
    criteria: list[Criterion] = Field(min_length=1)
    code_criteria: list[CodeCriterion] = []

    @field_validator("criteria")
    @classmethod
    def distinct_questions(cls, criteria: list[Criterion]) -> list[Criterion]:
        asks = [c.ask.strip().casefold() for c in criteria]
        repeated = sorted({c.ask.strip() for c in criteria if asks.count(c.ask.strip().casefold()) > 1})
        if repeated:
            raise ValueError(f"the same question is asked twice: {repeated}")
        return criteria


_NAMES = {"profile": "PROFILE", "criteria": "CRITERIA", "code_criteria": "CODE_CRITERIA"}


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
    label = item.get("ask") or item.get("type") if isinstance(item, dict) else None
    return f"{name}[{index}]" + (f" ({str(label)[:60]!r})" if label else "")


def load_settings(profile, criteria, code_criteria) -> Settings:
    """Validate the settings; raise SystemExit with one clear line per problem."""
    raw = {"profile": profile, "criteria": criteria, "code_criteria": code_criteria}
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

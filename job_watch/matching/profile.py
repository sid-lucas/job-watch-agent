"""The candidate profile (config.PROFILE_PATH, Markdown): personal data, read only at run time.

The only reader of the file. It checks the matching chain first: the profile is never read while
a cloud model could receive it. Also read here by the code, never by the LLM: the level of the line
that holds a quote ([Pro], [Projet], [Labo], [Cours], [En cours], "(ancien)") and the total
experience stated in the summary section ("0. Résumé").
"""
import hashlib
import re

from pydantic import BaseModel

from job_watch import config
from job_watch.llm import local_models
from job_watch.offers.criteria import _normal

LEVELS = ("Pro", "Projet", "Labo", "Cours", "En cours")
# Levels that cap a must requirement at "partial": theory only, still learning
WEAK_LEVELS = ("Cours", "En cours")
_TAG = re.compile(r"\[(pro|projet|labo|cours|en cours)\]")
_OLD = "(ancien)"


def read_profile() -> str:
    """Text of the profile; stops the program if MATCH_CHAIN holds a cloud model or the file is missing."""
    local_models(config.MATCH_CHAIN)
    if not config.PROFILE_PATH.is_file():
        raise SystemExit(f"Missing profile: {config.PROFILE_PATH} (see tests/fixtures/profile_example.md)")
    return config.PROFILE_PATH.read_text(encoding="utf-8")


def profile_id(profile: str) -> str:
    """Fingerprint of the profile: stored answers given on another profile are asked again."""
    return hashlib.sha256(profile.encode()).hexdigest()[:12]


class Level(BaseModel):
    level: str | None = None        # one of LEVELS, None when the line has no level
    old: bool = False               # "(ancien)": practised several years ago

    def text(self) -> str:
        return " ".join(filter(None, [f"[{self.level}]" if self.level else "", _OLD if self.old else ""])) or "-"


def level_of(profile: str, quote: str) -> Level:
    """Level of a quote of the profile: the first level tag of its line at or after the quote (the
    one that qualifies it in "SIEM [Pro], forensic [Cours]"), and "(ancien)" only when it follows
    that very tag (in "Python [Pro], Java [Cours] (ancien)", Python is not old). The first line
    holding the quote with a tag wins; none: no level."""
    wanted = _normal(quote)
    if not wanted:
        return Level()
    found = None
    for line in profile.splitlines():
        line = _normal(line)
        start = line.find(wanted)
        if start < 0:
            continue
        tag = _TAG.search(line, start)
        if tag is None:
            found = found or Level()
            continue
        after = line[tag.end():]
        next_part = re.split(r"[,;\[]", after, maxsplit=1)[0]
        level = next(name for name in LEVELS if name.casefold() == tag.group(1))
        return Level(level=level, old=_OLD in next_part)
    return found or Level()


def _summary(profile: str) -> str:
    """Text of the section "0. Résumé" (up to the next heading of the same or a higher level)."""
    lines, inside, depth = [], False, 0
    for line in profile.splitlines():
        heading = re.match(r"(#+)\s*(.*)", line)
        if heading and inside and len(heading.group(1)) <= depth:
            break
        if heading and re.match(r"0[.)]?\s", heading.group(2)):
            inside, depth = True, len(heading.group(1))
            continue
        if inside:
            lines.append(line)
    return "\n".join(lines)


def total_years(profile: str) -> float | None:
    """Total experience in years, from the line "Expérience totale" of the summary; None when absent."""
    for line in _summary(profile).splitlines():
        if "expérience totale" in line.casefold() or "experience totale" in line.casefold():
            number = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:ans?|years?)\b", line, re.IGNORECASE)
            if number:
                return float(number.group(1).replace(",", "."))
    return None

"""The candidate profile (config.PROFILE_PATH, Markdown): personal data, read only at run time.

The only reader of the file. It checks the matching chain first: the profile is never read while
a cloud model could receive it. Also read here by the code, never by the LLM:
- the numbered lines of the profile (L1, L2..., each with the title of its section): the LLM answers
  with line ids, the code reads the lines itself, so a proof cannot be paraphrased;
- the level of a line for a requirement ([Pro], [Projet], [Labo], [Cours], [En cours], "(ancien)");
- the level of a language (CEFR, and the usual words);
- the total experience stated in the summary section ("0. Résumé").
Format of the profile: sections "## N. Title" (see tests/fixtures/profile_example.md).
"""
import hashlib
import re
import unicodedata

from pydantic import BaseModel

from job_watch import config
from job_watch.llm import local_models
from job_watch.offers.criteria import _normal

LEVELS = ("Pro", "Projet", "Labo", "Cours", "En cours")
# Levels that cap a must requirement at "partial": theory only, still learning
WEAK_LEVELS = ("Cours", "En cours")
_OLD = "(ancien)"
_SEGMENT = re.compile(r"(.*?)\[(pro|projet|labo|cours|en cours)\]\s*(\(ancien\))?")
# Words of a requirement label that do not name the skill itself
_STOP_WORDS = {"experience", "knowledge", "skills", "skill", "years", "year", "with", "and", "in", "of", "the",
               "or", "de", "et", "en", "des", "la", "le", "du", "un", "une", "strong", "good", "basic"}

# Language levels: CEFR A1 < A2 < B1 < B2 < C1 < C2, a native language above C2
CEFR = ("A1", "A2", "B1", "B2", "C1", "C2")
NATIVE = 7
_LANGUAGE_WORDS = {"langue maternelle": NATIVE, "maternelle": NATIVE, "native": NATIVE, "mother tongue": NATIVE,
                   "muttersprache": NATIVE, "bilingue": NATIVE, "bilingual": NATIVE,
                   "courant": 5, "fluent": 5, "fluently": 5, "fließend": 5, "verhandlungssicher": 5,
                   "intermédiaire": 3, "intermediate": 3,
                   "notions": 2, "basic": 2, "grundkenntnisse": 2,
                   "débutant": 1, "beginner": 1}


def read_profile() -> str:
    """Text of the profile; stops the program if MATCH_CHAIN holds a cloud model or the file is missing."""
    local_models(config.MATCH_CHAIN)
    if not config.PROFILE_PATH.is_file():
        raise SystemExit(f"Missing profile: {config.PROFILE_PATH} (see tests/fixtures/profile_example.md)")
    return config.PROFILE_PATH.read_text(encoding="utf-8")


def profile_id(profile: str) -> str:
    """Fingerprint of the profile: stored answers given on another profile are asked again."""
    return hashlib.sha256(profile.encode()).hexdigest()[:12]


def section_key(title: str) -> str:
    """Name of a section to compare: number, accents and case dropped ("0. Résumé" -> "resume")."""
    title = re.sub(r"^\s*\d+[.)]?\s*", "", title)
    folded = unicodedata.normalize("NFKD", title)
    return " ".join("".join(c for c in folded if not unicodedata.combining(c)).casefold().split())


class ProfileLine(BaseModel):
    id: str             # "L12"
    section: str        # title of its section, as written ("2. Expérience professionnelle")
    text: str


def profile_lines(profile: str) -> list[ProfileLine]:
    """Every line of the profile with content, numbered, with the title of its section. Section
    headings ("## N. Title") and table separators are not lines; sub-headings ("### ...") are."""
    found, section = [], ""
    for raw in profile.splitlines():
        text = raw.strip()
        heading = re.match(r"(#+)\s*(.*)", text)
        if not text or (heading and len(heading.group(1)) <= 2):
            if heading and len(heading.group(1)) == 2:
                section = heading.group(2).strip()
            continue
        if re.fullmatch(r"\|?[\s:|-]+\|?", text):
            continue
        found.append(ProfileLine(id=f"L{len(found) + 1}", section=section, text=text))
    return found


def numbered(lines: list[ProfileLine]) -> str:
    """The profile as sent to the local model: one line per id, with its section."""
    return "\n".join(f"{line.id} [{line.section}] {line.text}" for line in lines)


class Level(BaseModel):
    level: str | None = None        # one of LEVELS, None when unknown
    old: bool = False               # "(ancien)": practised several years ago

    def text(self) -> str:
        return " ".join(filter(None, [f"[{self.level}]" if self.level else "", _OLD if self.old else ""])) or "-"

    def rank(self) -> tuple[bool, float]:
        """Higher is stronger: not old first, then Pro > Projet > Labo > unknown > Cours > En cours."""
        order = {"Pro": 5, "Projet": 4, "Labo": 3, None: 2.5, "Cours": 2, "En cours": 1}
        return not self.old, order[self.level]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W_]{2,}", _normal(text)) if w not in _STOP_WORDS}


def line_level(text: str, names: list[str]) -> Level:
    """Level of a line of the profile for a requirement named by `names` (label, option). A line with
    one level tag: that tag. With several ("Python [Pro], Java [Cours] (ancien)"): the tag of the
    part that names the requirement; none named: unknown. "(ancien)" counts right after its tag only."""
    normal = _normal(text)
    segments = [(m.group(1), m.group(2), bool(m.group(3))) for m in _SEGMENT.finditer(normal)]
    if not segments:
        return Level(old=_OLD in normal)
    if len(segments) > 1:
        wanted = set().union(*(_words(name) for name in names)) if names else set()
        overlap = [(len(wanted & _words(part)), number) for number, (part, _, _) in enumerate(segments)]
        best, number = max(overlap, key=lambda item: (item[0], -item[1]))
        if not best:
            return Level()
        segments = [segments[number]]
    _, tag, old = segments[0]
    return Level(level=next(name for name in LEVELS if name.casefold() == tag), old=old)


def language_level(text: str) -> int | None:
    """Level of a language, 1 (A1) to 6 (C2), 7 for a native language; None when not stated.
    A table row of the Langues section is read in its level column (the second one)."""
    cells = [cell.strip() for cell in text.strip().strip("|").split("|")]
    if len(cells) >= 2 and text.strip().startswith("|"):
        text = cells[1]
    normal = _normal(text)
    code = re.search(r"\b([abc][12])\b", normal)
    if code:
        return CEFR.index(code.group(1).upper()) + 1
    words = [(len(word), value) for word, value in _LANGUAGE_WORDS.items() if re.search(rf"\b{word}\b", normal)]
    return max(words)[1] if words else None


def language_name(level: int | None) -> str:
    return "-" if level is None else "native" if level == NATIVE else CEFR[level - 1]


def total_years(profile: str) -> float | None:
    """Total experience in years, from the line "Expérience totale" of the summary; None when absent."""
    for line in profile_lines(profile):
        if section_key(line.section) == "resume" and "experience totale" in section_key(line.text):
            number = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:ans?|years?)\b", line.text, re.IGNORECASE)
            if number:
                return float(number.group(1).replace(",", "."))
    return None

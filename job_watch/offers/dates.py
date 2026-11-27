"""Publication date of an offer read by the code from a relative date in its page ("Posted 3 Days Ago",
"il y a 3 jours", "vor 3 Tagen"), counted back from the day the page was read.

General vocabulary (EN, FR, DE), never per site. The first relative date of the page is the one of
the offer: a page that lists other offers further down ("Similar jobs") gives their dates later.
An open bound ("30+ days ago") gives no date: an unknown date never takes points away.
"""
import re
import unicodedata
from datetime import date, timedelta

_NUMBER = r"(?P<n>\d{1,3})(?P<plus>\+?)"
_DAY = {"day": 1, "week": 7, "month": 30}
# (pattern, unit), on folded text: lower case, no accents
_PATTERNS = [
    (rf"(?:posted\s+)?{_NUMBER}\s*(?P<unit>day|week|month)s?\s+ago", None),
    (rf"il\s+y\s+a\s+{_NUMBER}\s*(?P<unit>jour|semaine|mois)s?", {"jour": 1, "semaine": 7, "mois": 30}),
    (rf"vor\s+{_NUMBER}\s*(?P<unit>tag|woche|monat)(?:en|e|n)?\b", {"tag": 1, "woche": 7, "monat": 30}),
    (r"posted\s+(?P<word>today|yesterday)", {"today": 0, "yesterday": 1}),
    (r"publiee?\s+(?P<word>aujourd'hui|hier)", {"aujourd'hui": 0, "hier": 1}),
    (r"veroffentlicht\s+(?P<word>heute|gestern)", {"heute": 0, "gestern": 1}),
]
_COMPILED = [(re.compile(rf"(?<![\w-]){pattern}(?![\w-])"), units) for pattern, units in _PATTERNS]


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().replace("’", "'")


def posted_in_text(text: str, read_on: date) -> date | None:
    """Publication date from the first relative date of the text, or None."""
    folded = _fold(text)
    found = [(m.start(), m, units) for pattern, units in _COMPILED for m in [pattern.search(folded)] if m]
    if not found:
        return None
    _, match, units = min(found, key=lambda item: item[0])
    groups = match.groupdict()
    if groups.get("word"):
        return read_on - timedelta(days=units[groups["word"]])
    if groups["plus"]:
        return None                     # "30+ days ago": only a lower bound
    days = int(groups["n"]) * (units or _DAY)[groups["unit"]]
    return read_on - timedelta(days=days)

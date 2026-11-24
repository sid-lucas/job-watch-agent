import re

# Common German words that are not French or English words
GERMAN_STOPWORDS = {
    "und", "der", "die", "das", "wir", "mit", "für", "bei", "sowie", "deine",
    "dich", "dein", "bist", "oder", "ist", "von", "zu", "auf", "ein", "eine",
}


def is_german_ad(text: str, threshold: float = 0.04) -> bool:
    """Return True when the text is mostly written in German."""
    words = re.findall(r"\b\w+\b", text.lower())
    if not words:
        return False
    hits = sum(word in GERMAN_STOPWORDS for word in words)
    return hits / len(words) > threshold

def names_pattern(names: list[str]) -> str:
    """Build a whole-word regex matching any of the given names."""
    return r"\b(" + "|".join(re.escape(name) for name in names) + r")\b"
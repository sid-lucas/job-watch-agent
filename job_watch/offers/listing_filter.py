"""Filter on listed offers, in code: IT title and location in Switzerland.

Only the listing is known at this point (title and location, no description), so the
keywords of user_config are searched in the title alone, with the V1 rule (whole words,
case-insensitive). An unknown location is kept: the detail page will tell.

The place names are general Swiss geography (country, cantons, towns), never per-site rules.
A Swiss town missing from the list makes an offer not kept: the list errs toward size, and
listed_offers keeps every offer, kept or not.
"""
import re
import unicodedata

from job_watch import config
from job_watch.list_agent.extraction import CheckedOffer

SWISS_WORDS = {
    # country
    "switzerland", "suisse", "schweiz", "svizzera", "svizra", "swiss",
    # cantons (names in the local languages and in English or French)
    "zurich", "zuerich", "bern", "berne", "luzern", "lucerne", "uri", "schwyz", "obwalden", "nidwalden",
    "glarus", "glaris", "zug", "zoug", "fribourg", "freiburg", "solothurn", "soleure", "basel", "bale",
    "basel-stadt", "basel-landschaft", "schaffhausen", "schaffhouse", "appenzell", "st. gallen", "st gallen",
    "sankt gallen", "saint-gall", "graubunden", "grisons", "aargau", "argovie", "thurgau", "thurgovie",
    "ticino", "tessin", "vaud", "valais", "wallis", "neuchatel", "geneve", "geneva", "genf", "ginevra",
    "jura",
    # towns
    "winterthur", "lausanne", "lugano", "biel", "bienne", "biel/bienne", "thun", "koniz", "la chaux-de-fonds",
    "chur", "vernier", "uster", "sion", "emmen", "lancy", "yverdon", "yverdon-les-bains", "kriens",
    "rapperswil", "dubendorf", "montreux", "meyrin", "nyon", "vevey", "plan-les-ouates", "carouge",
    "morges", "renens", "baden", "aarau", "olten", "bellinzona", "locarno", "mendrisio", "le locle",
    "le brassus", "le sentier", "grenchen", "granges", "bulle", "delemont", "porrentruy", "martigny",
    "monthey", "sierre", "frauenfeld", "wil", "herisau", "liestal", "altdorf", "sarnen", "stans",
    "opfikon", "wallisellen", "kloten", "glattbrugg", "schlieren", "dietikon", "zollikon", "kusnacht",
    "horgen", "thalwil", "ecublens", "epalinges", "gland", "rolle", "prilly", "pully", "crissier",
    "satigny", "bussigny", "nidau", "saint-imier", "villeret", "fleurier", "versoix", "chene-bourg",
    "grand-saconnex", "le grand-saconnex", "cologny", "thonex", "onex", "manno", "chiasso", "neuhausen",
    "schaffhouse", "rotkreuz", "baar", "cham", "pfaffikon", "allschwil", "muttenz", "pratteln", "reinach",
    "riehen", "binningen", "langenthal", "burgdorf", "spiez", "interlaken", "visp", "brig", "davos",
    "st. moritz", "bulach", "wetzikon", "zofingen", "wohlen", "lenzburg", "brugg", "solothurn",
}
# Canton and country codes: upper case whole words only ("GE" in "Meyrin, GE"), never lower case words
SWISS_CODES = {
    "CH", "ZH", "BE", "LU", "UR", "SZ", "OW", "NW", "GL", "ZG", "FR", "SO", "BS", "BL", "SH", "AR", "AI",
    "SG", "GR", "AG", "TG", "TI", "VD", "VS", "NE", "GE", "JU",
}


def _fold(text: str) -> str:
    """Lower case, no accents, single spaces."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().casefold()


_SWISS_WORDS = re.compile(r"(?<![\w-])(?:" + "|".join(sorted((re.escape(w) for w in SWISS_WORDS), key=len,
                                                              reverse=True)) + r")(?![\w-])")
_SWISS_CODES = re.compile(r"(?<![\w-])(?:" + "|".join(sorted(SWISS_CODES)) + r")(?![\w-])")


def is_it_title(title: str) -> bool:
    """At least one keyword of user_config in the title (whole words, case-insensitive, as in V1)."""
    return any(re.search(rf"\b{re.escape(k)}\b", title, re.IGNORECASE) for k in config.KEYWORDS)


def in_switzerland(location: str) -> bool | None:
    """True for a Swiss place, False for another one, None when the location is unknown."""
    if not location.strip() or _fold(location) == "unknown":
        return None
    return bool(_SWISS_WORDS.search(_fold(location)) or _SWISS_CODES.search(location))


def keep(offer: CheckedOffer) -> bool:
    """IT title, and location in Switzerland or unknown."""
    return is_it_title(offer.title) and in_switzerland(offer.location) is not False

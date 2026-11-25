"""Filter on listed offers, in code: IT title, and location not clearly abroad.

Only the listing is known at this point (title and location, no description), so the
keywords of user_config are searched in the title alone, with the V1 rule (whole words,
case-insensitive).

Funnel principle: a lost offer costs more than an extra one. An offer is set aside only when
its location is clearly abroad (another country, or a large foreign city) and names no Swiss
place. Everything else is kept: Swiss place, unknown town (a small Swiss town missing from
the list), "Remote", "Multiple locations", unknown location.

The place names are general geography, never per-site rules.
"""
import re
import unicodedata
from typing import Literal

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
FOREIGN_WORDS = {
    # countries (English, and the local or French, German, Italian names when they differ)
    "france", "germany", "deutschland", "allemagne", "germania", "italy", "italia", "italie", "italien",
    "austria", "osterreich", "autriche", "united kingdom", "uk", "england", "angleterre", "great britain",
    "scotland", "ireland", "irland", "spain", "espana", "espagne", "spanien", "portugal", "netherlands",
    "nederland", "pays-bas", "niederlande", "belgium", "belgique", "belgien", "luxembourg", "luxemburg",
    "liechtenstein", "monaco", "poland", "polska", "pologne", "polen", "czech republic", "czechia",
    "slovakia", "hungary", "romania", "bulgaria", "croatia", "serbia", "slovenia", "greece", "sweden",
    "norway", "denmark", "finland", "estonia", "latvia", "lithuania", "united states", "usa", "u.s.",
    "etats-unis", "vereinigte staaten", "canada", "mexico", "brazil", "bresil", "argentina", "chile",
    "colombia", "peru", "china", "chine", "hong kong", "taiwan", "japan", "japon", "korea", "south korea",
    "singapore", "singapour", "india", "inde", "indonesia", "malaysia", "thailand", "vietnam",
    "philippines", "australia", "australie", "new zealand", "united arab emirates", "uae", "qatar",
    "saudi arabia", "bahrain", "kuwait", "israel", "turkey", "turkiye", "egypt", "morocco", "maroc",
    "tunisia", "south africa", "nigeria", "kenya", "russia", "ukraine",
    # large foreign cities
    "london", "londres", "paris", "lyon", "marseille", "lille", "toulouse", "berlin", "munich", "munchen",
    "frankfurt", "francfort", "hamburg", "dusseldorf", "cologne", "koln", "stuttgart", "vienna", "wien",
    "vienne", "milan", "milano", "rome", "roma", "turin", "torino", "madrid", "barcelona", "lisbon",
    "lisboa", "lisbonne", "porto", "amsterdam", "rotterdam", "brussels", "bruxelles", "dublin", "warsaw",
    "warszawa", "krakow", "wroclaw", "prague", "praha", "budapest", "bucharest", "sofia", "athens",
    "stockholm", "oslo", "copenhagen", "helsinki", "new york", "san francisco", "boston", "chicago",
    "los angeles", "miami", "houston", "dallas", "seattle", "atlanta", "toronto", "montreal", "vancouver",
    "mexico city", "sao paulo", "buenos aires", "tokyo", "osaka", "shanghai", "beijing", "shenzhen",
    "seoul", "taipei", "mumbai", "bangalore", "bengaluru", "delhi", "new delhi", "chennai", "hyderabad",
    "pune", "kuala lumpur", "bangkok", "jakarta", "manila", "ho chi minh", "sydney", "melbourne",
    "dubai", "abu dhabi", "doha", "riyadh", "tel aviv", "istanbul", "johannesburg", "cape town", "cairo",
    "moscow",
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
_FOREIGN_WORDS = re.compile(r"(?<![\w-])(?:" + "|".join(sorted((re.escape(w) for w in FOREIGN_WORDS), key=len,
                                                                  reverse=True)) + r")(?![\w-])")
_SWISS_CODES = re.compile(r"(?<![\w-])(?:" + "|".join(sorted(SWISS_CODES)) + r")(?![\w-])")


def is_it_title(title: str) -> bool:
    """At least one keyword of user_config in the title (whole words, case-insensitive, as in V1)."""
    return any(re.search(rf"\b{re.escape(k)}\b", title, re.IGNORECASE) for k in config.KEYWORDS)


LocationVerdict = Literal["switzerland", "abroad", "unknown"]


def location_verdict(location: str) -> LocationVerdict:
    """switzerland: a Swiss place is named. abroad: only a foreign country or large foreign city
    is named. unknown: anything else (empty, "unknown", "Remote", a town in neither list)."""
    folded = _fold(location)
    if _SWISS_WORDS.search(folded) or _SWISS_CODES.search(location):
        return "switzerland"
    if _FOREIGN_WORDS.search(folded):
        return "abroad"
    return "unknown"


def keep(offer: CheckedOffer) -> bool:
    """IT title, and location not clearly abroad."""
    return is_it_title(offer.title) and location_verdict(offer.location) != "abroad"

"""Location of an offer: in Switzerland, clearly abroad, or unknown."""
import pytest

from job_watch.offers.listing_filter import location_verdict


@pytest.mark.parametrize("location, expected", [
    ("Meyrin, GE, Switzerland", "switzerland"),
    ("Genève", "switzerland"),
    ("Zurich", "switzerland"),
    ("Le Brassus", "switzerland"),
    ("Biel/Bienne", "switzerland"),
    ("Lugano, TI", "switzerland"),
    ("St. Gallen", "switzerland"),
    ("Geneva or London", "switzerland"),        # one Swiss place is enough
    ("Geneva, Illinois", "switzerland"),        # known false positive: kept, the funnel prefers it
    ("Singapore", "abroad"),
    ("London, United Kingdom", "abroad"),
    ("New York, NY", "abroad"),
    ("Lyon, France", "abroad"),
    ("Remote - Germany", "abroad"),
    ("Gossau", "unknown"),                      # small Swiss town missing from the list
    ("Remote", "unknown"),
    ("Multiple locations", "unknown"),
    ("unknown", "unknown"),
    ("", "unknown"),
])
def test_location_verdict(location, expected):
    assert location_verdict(location) == expected


def test_codes_and_names_are_whole_words_only():
    assert location_verdict("Basel-Stadt") == "switzerland"
    assert location_verdict("Bernalillo") == "unknown"          # "bern" inside a longer word
    assert location_verdict("Parisot") == "unknown"             # "paris" inside a longer word
    assert location_verdict("fr") == "unknown"                  # codes count in upper case only

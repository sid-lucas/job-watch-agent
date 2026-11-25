"""Filter on listed offers: IT title (keywords of user_config), location not clearly abroad."""
import pytest

from job_watch.list_agent.extraction import CheckedOffer
from job_watch.offers import listing_filter
from job_watch.offers.listing_filter import is_it_title, keep, location_verdict


@pytest.fixture(autouse=True)
def keywords(monkeypatch):
    # Fixed keywords: the test does not depend on the personal user_config.py
    monkeypatch.setattr(listing_filter.config, "KEYWORDS", ["security", "cyber", "soc"])


def offer(title, location):
    return CheckedOffer(title=title, location=location, link="", reference="", verified=False, key="k")


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


@pytest.mark.parametrize("title, expected", [
    ("Security Engineer (m/w)", True),
    ("SOC Analyst", True),
    ("Cyber Defence Specialist", True),
    ("Associate, Socially Responsible Investment", False),  # "soc" inside a word
    ("Client Advisor", False),
])
def test_it_titles(title, expected):
    assert is_it_title(title) is expected


def test_keep_needs_an_it_title_and_a_location_not_clearly_abroad():
    assert keep(offer("Security Engineer", "Geneva"))
    assert keep(offer("Security Engineer", "unknown"))
    assert keep(offer("Security Engineer", "Remote"))
    assert keep(offer("Security Engineer", "Gossau"))
    assert not keep(offer("Security Engineer", "Singapore"))
    assert not keep(offer("Client Advisor", "Geneva"))


def test_keep_plugs_into_listed_offers(tmp_path):
    from job_watch.offers.listed import connect, save_listed_offers
    conn = connect(tmp_path / "test.db")
    offers = [offer("Security Engineer", "Zurich"), offer("Client Advisor", "Zurich")]
    offers[1].key = "k2"
    save_listed_offers(conn, "Bank", offers, "2026-11-25", keep=keep)
    assert conn.execute("SELECT key, kept FROM listed_offers ORDER BY key").fetchall() == [("k", 1), ("k2", 0)]
    conn.close()

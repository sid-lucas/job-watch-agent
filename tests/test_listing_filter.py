"""Filter on listed offers: IT title (keywords of user_config) and Swiss location."""
import pytest

from job_watch.list_agent.extraction import CheckedOffer
from job_watch.offers import listing_filter
from job_watch.offers.listing_filter import in_switzerland, is_it_title, keep


@pytest.fixture(autouse=True)
def keywords(monkeypatch):
    # Fixed keywords: the test does not depend on the personal user_config.py
    monkeypatch.setattr(listing_filter.config, "KEYWORDS", ["security", "cyber", "soc"])


def offer(title, location):
    return CheckedOffer(title=title, location=location, link="", reference="", verified=False, key="k")


@pytest.mark.parametrize("location, expected", [
    ("Meyrin, GE, Switzerland", True),
    ("Genève", True),
    ("Zurich", True),
    ("Bern, Switzerland", True),
    ("Le Brassus", True),
    ("Biel/Bienne", True),
    ("Plan-les-Ouates", True),
    ("Lugano, TI", True),
    ("St. Gallen", True),
    ("Singapore", False),
    ("London, United Kingdom", False),
    ("New York, NY", False),
    ("Geneva, Illinois", True),         # known false positive: the town name wins
    ("unknown", None),
    ("", None),
])
def test_swiss_locations(location, expected):
    assert in_switzerland(location) is expected


def test_codes_are_upper_case_whole_words_only():
    assert in_switzerland("Lyon, France") is False         # "fr" inside a word, lower case
    assert in_switzerland("Basel-Stadt") is True
    assert in_switzerland("Bernalillo") is False             # "bern" inside a longer word


@pytest.mark.parametrize("title, expected", [
    ("Security Engineer (m/w)", True),
    ("SOC Analyst", True),
    ("Cyber Defence Specialist", True),
    ("Associate, Socially Responsible Investment", False),  # "soc" inside a word
    ("Client Advisor", False),
])
def test_it_titles(title, expected):
    assert is_it_title(title) is expected


def test_keep_needs_an_it_title_and_a_swiss_or_unknown_location():
    assert keep(offer("Security Engineer", "Geneva"))
    assert keep(offer("Security Engineer", "unknown"))
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

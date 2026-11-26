"""Filter on listed offers: category from the triage, location not clearly abroad."""
import pytest

from job_watch.list_agent.extraction import CheckedOffer
from job_watch.offers import listing_filter
from job_watch.offers.listing_filter import keep, location_verdict


def offer(title, location, category="Cybersecurity SOC/incident response"):
    return CheckedOffer(title=title, location=location, link="", reference="", verified=False, key="k",
                        category=category)


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


def test_keep_needs_a_kept_category_and_a_location_not_clearly_abroad():
    assert keep(offer("Security Engineer", "Geneva"))
    assert keep(offer("Security Engineer", "unknown"))
    assert keep(offer("Security Engineer", "Remote"))
    assert keep(offer("Security Engineer", "Gossau"))
    assert not keep(offer("Security Engineer", "Singapore"))
    assert not keep(offer("Client Advisor", "Geneva", "Banking/investment/wealth management"))
    assert not keep(offer("Huissier sécurité", "Geneva", "Physical security/safety"))


def test_an_offer_without_a_stated_category_is_kept():
    assert keep(offer("Something", "Geneva", "Unclear"))
    assert keep(offer("Something", "Geneva", None))                       # not triaged


def test_keep_plugs_into_listed_offers(tmp_path):
    from job_watch.offers.listed import connect, save_listed_offers
    conn = connect(tmp_path / "test.db")
    offers = [offer("Security Engineer", "Zurich"),
              offer("Client Advisor", "Zurich", "Banking/investment/wealth management")]
    offers[1].key = "k2"
    save_listed_offers(conn, "Bank", offers, "2026-11-25", keep=keep)
    assert conn.execute("SELECT key, kept FROM listed_offers ORDER BY key").fetchall() == [("k", 1), ("k2", 0)]
    conn.close()

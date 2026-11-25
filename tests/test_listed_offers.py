"""listed_offers table, on a temporary database (never data/offers.db)."""
import pytest

from job_watch.list_agent.extraction import CheckedOffer
from job_watch.offers.listed import connect, save_listed_offers


def offer(title, key, location="Geneva", link="", verified=False):
    return CheckedOffer(title=title, location=location, link=link, reference="", verified=verified, key=key)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    yield connection
    connection.close()


def rows(conn):
    return conn.execute("SELECT company, key, title, first_seen, last_seen, kept FROM listed_offers "
                        "ORDER BY company, key").fetchall()


def test_new_offers_are_inserted_and_known_ones_only_get_last_seen(conn):
    first = [offer("Analyst", "ref:1"), offer("Engineer", "ref:2")]
    assert save_listed_offers(conn, "Bank", first, "2026-11-25") == ["ref:1", "ref:2"]
    # Next run: one known offer with a changed title, one new offer
    second = [offer("Analyst (renamed)", "ref:1"), offer("Tester", "ref:3")]
    assert save_listed_offers(conn, "Bank", second, "2026-11-26") == ["ref:3"]
    assert rows(conn) == [("Bank", "ref:1", "Analyst", "2026-11-25", "2026-11-26", None),
                          ("Bank", "ref:2", "Engineer", "2026-11-25", "2026-11-25", None),
                          ("Bank", "ref:3", "Tester", "2026-11-26", "2026-11-26", None)]


def test_the_same_key_in_two_companies_is_two_offers(conn):
    save_listed_offers(conn, "Bank", [offer("Analyst", "ref:1")], "2026-11-25")
    assert save_listed_offers(conn, "Watchmaker", [offer("Watchmaker", "ref:1")], "2026-11-25") == ["ref:1"]
    assert len(rows(conn)) == 2


def test_kept_is_set_on_insert_only(conn):
    save_listed_offers(conn, "Bank", [offer("Analyst", "ref:1")], "2026-11-25", keep=lambda o: True)
    save_listed_offers(conn, "Bank", [offer("Analyst", "ref:1")], "2026-11-26", keep=lambda o: False)
    assert rows(conn)[0][-1] == 1


def test_an_offer_without_key_is_refused(conn):
    with pytest.raises(ValueError):
        save_listed_offers(conn, "Bank", [offer("Analyst", "")], "2026-11-25")
    assert rows(conn) == []


def test_page_text_is_stored_as_data(conn):
    hostile = "x'); DROP TABLE listed_offers; --"
    save_listed_offers(conn, "Bank", [offer(hostile, "text:abc")], "2026-11-25")
    assert rows(conn)[0][2] == hostile

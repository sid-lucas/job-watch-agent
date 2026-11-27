"""RSS feeds of user_config.py: validation, one source per feed, domain triage only where asked (no LLM)."""
from types import SimpleNamespace

import pytest

from helpers import criteria_settings
from job_watch import config
from job_watch.offers import nodes, storage
from job_watch.offers.triage import Triage

CRITERIA = [{"ask": "Is it a SOC job?", "points": 30}]


def feed(name, triage, url=None):
    return {"name": name, "url": url or f"https://{name}.example/rss", "triage": triage}


@pytest.fixture(autouse=True)
def temporary_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "offers.db")


@pytest.mark.parametrize("feeds, expected", [
    ([{"name": "a", "url": "https://a.example/rss"}], "triage: missing key"),
    ([feed("a", True, url="ftp://a.example/rss")], "url"),
    ([feed("a", True), feed("A", False)], "two feeds have the same name"),
    ([feed("career_site", True)], "source name of career-site offers"),
    ([{**feed("a", True), "trige": True}], "unknown key"),
])
def test_a_bad_feed_is_named_in_the_error(feeds, expected):
    with pytest.raises(SystemExit) as raised:
        criteria_settings(CRITERIA, rss_feeds=feeds)
    assert "RSS_FEEDS" in str(raised.value) and expected in str(raised.value)


def test_each_feed_is_read_and_its_name_is_the_source(monkeypatch):
    monkeypatch.setattr(config, "SETTINGS", criteria_settings(CRITERIA, rss_feeds=[feed("board", False),
                                                                                  feed("general", True)]))
    entries = {"https://board.example/rss": [("SOC Analyst @ Bank [CHF 100k]", "https://board.example/1")],
               "https://general.example/rss": [("Accountant @ Shop", "https://general.example/2?utm=x")]}

    class Entry(dict):              # feedparser entries: attributes and dict access
        __getattr__ = dict.__getitem__
    monkeypatch.setattr(nodes.feedparser, "parse", lambda url: SimpleNamespace(
        entries=[Entry(title=t, link=l, description="Salary: CHF 1 per year\nText", published="")
                 for t, l in entries[url]]))
    offers = nodes.fetch_rss({"offers": []})["offers"]
    assert [(o["source"], o["title"], o["company"], o["link"], o["description"]) for o in offers] == [
        ("board", "SOC Analyst", "Bank", "https://board.example/1", "Text"),
        ("general", "Accountant", "Shop", "https://general.example/2", "Text")]


def test_the_domain_triage_runs_only_on_feeds_that_ask_for_it(monkeypatch):
    monkeypatch.setattr(config, "SETTINGS", criteria_settings(CRITERIA, rss_feeds=[feed("board", False),
                                                                                  feed("general", True)]))
    asked = []

    def fake_triage(offers, log=None, models=None):
        asked.extend(o.title for o in offers)
        return [Triage(domain="Finance, banking & accounting", answered=True) for _ in offers]
    monkeypatch.setattr(nodes, "triage_offers", fake_triage)
    offers = [{"key": storage.rss_key(f"https://{s}.example/1"), "title": t, "company": "Bank", "location": "unknown",
               "description": "", "source": s, "link": f"https://{s}.example/1", "published": "", "fetched": ""}
              for s, t in (("board", "SOC Analyst"), ("general", "Accountant"))]
    triaged = {o["title"]: o.get("domain") for o in nodes.triage_rss({"offers": offers})["offers"]}
    assert asked == ["Accountant"]
    assert triaged == {"SOC Analyst": None, "Accountant": "Finance, banking & accounting"}    # None: kept

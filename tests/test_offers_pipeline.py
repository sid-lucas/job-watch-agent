"""V1 pipeline with career sites: offers table, migration, node, conversion (no LLM, no browser).

Every database and registry is temporary: data/ is never touched.
"""
import json
import sqlite3

import pytest

from job_watch import config
from job_watch.list_agent.collect import CompanyCollection, DetailCollection
from job_watch.list_agent.detail import CheckedDetail
from job_watch.list_agent.extraction import CheckedOffer
from job_watch.offers import career_sites, storage
from job_watch.offers.nodes import deduplicate


@pytest.fixture(autouse=True)
def temporary_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "offers.db")
    monkeypatch.setattr(config, "REGISTRY_PATH", tmp_path / "registry.json")
    return tmp_path


def rss_offer(link, title="Security Engineer", company="Bank"):
    return {"key": storage.rss_key(link), "title": title, "company": company, "location": "unknown",
            "description": "text", "source": "swissdevjobs", "link": link, "published": "", "fetched": "",
            "score": 30, "reasons": ["security title (+30)"], "status": "new"}


def test_a_v1_table_is_migrated_without_losing_offers():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""CREATE TABLE offers (link TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT, location TEXT,
                    description TEXT, source TEXT, published TEXT, fetched TEXT, score INTEGER, reasons TEXT,
                    status TEXT)""")
    conn.executemany("INSERT INTO offers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        ("https://a.example/1", "SOC Analyst", "Bank", "unknown", "d1", "swissdevjobs", "", "", 30, "[]", "new"),
        ("https://a.example/2", "Pentester", None, "unknown", "d2", "swissdevjobs", "", "", 0, "[]", "rejected")])
    conn.commit()
    conn.close()

    migrated = storage.connect()
    rows = migrated.execute("SELECT company, key, link, title, score, status FROM offers ORDER BY key").fetchall()
    migrated.close()
    assert rows == [("Bank", "url:https://a.example/1", "https://a.example/1", "SOC Analyst", 30, "new"),
                    ("unknown", "url:https://a.example/2", "https://a.example/2", "Pentester", 0, "rejected")]
    # An RSS offer seen again after the migration is not new
    assert storage.save_offers([rss_offer("https://a.example/1", "SOC Analyst")]) == []


def test_save_offers_uses_company_and_key():
    first = [rss_offer("https://a.example/1"), rss_offer("https://a.example/1")]    # same offer twice
    assert storage.save_offers(first) == [("Bank", "url:https://a.example/1")]
    career = {**rss_offer(""), "key": "ref:12", "company": "Watchmaker", "source": "career_site",
              "requirements": ["5 years of Kubernetes"], "contract": "permanent"}
    other = {**career, "company": "Bank"}                                            # same key, other company
    assert storage.save_offers([career, other]) == [("Watchmaker", "ref:12"), ("Bank", "ref:12")]
    conn = storage.connect()
    stored = conn.execute("SELECT requirements, contract FROM offers WHERE company = 'Watchmaker'").fetchone()
    conn.close()
    assert json.loads(stored[0]) == ["5 years of Kubernetes"] and stored[1] == "permanent"


def test_offers_without_link_are_not_duplicates_of_each_other():
    offers = [{**rss_offer(""), "title": "Analyst"}, {**rss_offer(""), "title": "Engineer"},
              {**rss_offer("https://a.example/1"), "title": "Tester"},
              {**rss_offer("https://a.example/1"), "title": "Tester (copy)"}]
    assert [o["title"] for o in deduplicate({"offers": offers})["offers"]] == ["Analyst", "Engineer", "Tester"]


def test_registry_companies_with_a_job_list():
    registry = {"Bank": {"status": "ok", "jobs_url": "https://bank.example/jobs"},
                "Blocked": {"status": "blocked", "jobs_url": "https://blocked.example/jobs"},
                "None": {"status": "not_found", "jobs_url": None},
                "Watchmaker": {"status": "ok", "jobs_url": "https://watch.example/jobs"}}
    assert career_sites.registry_companies(registry) == [("Bank", "https://bank.example/jobs"),
                                                         ("Watchmaker", "https://watch.example/jobs")]
    assert career_sites.registry_companies(registry, ["watchmaker"]) == [("Watchmaker", "https://watch.example/jobs")]


def listed(key, title, link=""):
    return CheckedOffer(title=title, location="Geneva", link=link, reference="", verified=bool(link), key=key)


def collection(company, offers):
    return CompanyCollection(company=company, url=f"https://{company.lower()}.example/jobs", stop="finish", seen="2026-11-25",
                             pages_reached=1, offers=offers, new_keys=[o.key for o in offers], new_kept=offers,
                             failed_chunks=0, model_calls={}, seconds=1)


def details(company, items, texts):
    return DetailCollection(company=company, details=items, texts=texts, refused_pages=[], failed_extractions=[],
                            skipped=[], model_calls={})


def checked_detail(key):
    return CheckedDetail(key=key, summary="Role.", requirements=["SIEM tools"], contract="internship",
                         contract_doubtful=False, workload="100 %", ad_language="en", required_languages=["fr"],
                         posted="2026-11-20", dropped_requirements=0)


def test_to_offers_keeps_offers_without_detail():
    found = career_sites.to_offers(
        collection("Bank", [listed("a", "Security Analyst", "https://bank.example/a"), listed("b", "SOC Analyst")]),
        details("Bank", [checked_detail("a")], {"a": "Security Analyst page text"}), "2026-11-25")
    assert [(o["key"], o["source"], o["description"], o.get("contract")) for o in found] == [
        ("a", "career_site", "Security Analyst page text", "internship"), ("b", "career_site", "", None)]
    assert found[0]["published"] == "2026-11-20" and found[1]["list_url"] == "https://bank.example/jobs"


def test_a_company_that_fails_does_not_stop_the_others(monkeypatch):
    config.REGISTRY_PATH.write_text(json.dumps({
        "Broken": {"status": "ok", "jobs_url": "https://broken.example/jobs"},
        "Bank": {"status": "ok", "jobs_url": "https://bank.example/jobs"}}))

    def fake_collect(company, url, conn, log=None):
        if company == "Broken":
            raise RuntimeError("browser crashed")
        return collection(company, [listed("a", "Security Analyst", "https://bank.example/a")])

    monkeypatch.setattr(career_sites, "collect_company", fake_collect)
    monkeypatch.setattr(career_sites, "collect_details",
                        lambda c, log=None: details(c.company, [checked_detail("a")], {"a": "text"}))
    result = career_sites.fetch_career_sites({"offers": [rss_offer("https://rss.example/1")],
                                              "sources": ["career_sites"]})
    assert [(o["company"], o["source"]) for o in result["offers"]] == [("Bank", "swissdevjobs"),
                                                                      ("Bank", "career_site")]


def test_career_sites_can_be_skipped():
    assert career_sites.fetch_career_sites({"offers": [], "sources": ["rss"]}) == {"offers": []}


def test_listed_offers_are_written_only_with_the_offers(monkeypatch):
    """A run that fails before or while storing marks nothing as seen: the offers stay new."""
    from job_watch.list_agent.collect import save_collection
    from job_watch.offers.listed import connect as connect_listed, known_keys
    from job_watch.offers.nodes import save_results
    connect_listed().close()                                   # tables created, as fetch_career_sites does
    found = collection("Bank", [listed("a", "Security Analyst", "https://bank.example/a")])
    offer = {**rss_offer("https://bank.example/a"), "key": "a", "source": "career_site"}

    # The collection alone (crash before save_results) writes nothing
    conn = connect_listed()
    assert known_keys(conn, "Bank") == set()

    # Storing fails: neither the offer nor the listed offer is written
    def broken(*args, **kwargs):
        raise RuntimeError("disk full")
    # A context, never monkeypatch.undo(): undo() would also restore config.DB_PATH (real data/)
    with monkeypatch.context() as patch:
        patch.setattr("job_watch.list_agent.collect.save_listed_offers", broken)
        with pytest.raises(RuntimeError):
            save_results({"offers": [offer], "collections": [found]})
    assert known_keys(conn, "Bank") == set()
    assert conn.execute("SELECT COUNT(*) FROM offers").fetchone() == (0,)

    # Storing succeeds: both are written
    assert save_results({"offers": [offer], "collections": [found]})["new_offers"] == [("Bank", "a")]
    assert known_keys(conn, "Bank") == {"a"}
    conn.close()
    assert save_collection is not None


def test_why_a_requested_company_is_not_collected():
    registry = {"Lombard Odier": {"status": "ok", "jobs_url": "https://lo.example/jobs"},
                "ICRC": {"status": "ok", "jobs_url": "https://icrc.example/jobs"},
                "Banque Cantonale Vaudoise": {"status": "blocked", "jobs_url": "https://bcv.example/jobs"},
                "Hublot": {"status": "ok", "jobs_url": None},
                "Rolex SA": {"status": "not_found", "jobs_url": None}}
    lines = career_sites.why_not_collected(
        registry, ["lombard odier", "Rolex", "Banque Cantonale Vaudoise", "Hublot", "Lombard Odiers", "Patek"])
    assert lines == [
        "Rolex: not in the registry; close names: Rolex SA",
        "Banque Cantonale Vaudoise: registry status 'blocked' (only 'ok' is collected)",
        "Hublot: no jobs_url in the registry",
        "Lombard Odiers: not in the registry; close names: Lombard Odier",
        "Patek: not in the registry",
    ]


def test_the_node_prints_why_a_company_is_not_collected(capsys):
    config.REGISTRY_PATH.write_text(json.dumps({"ICRC": {"status": "blocked", "jobs_url": "https://icrc.example"}}))
    career_sites.fetch_career_sites({"offers": [], "sources": ["career_sites"], "companies": ["ICRC", "Rolex"]})
    out = capsys.readouterr().out
    assert "fetch_career_sites: 0 companies" in out
    assert "not collected: ICRC: registry status 'blocked'" in out and "not collected: Rolex: not in the registry" in out

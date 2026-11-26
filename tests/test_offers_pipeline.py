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
    from helpers import checked_detail as build
    return build(key, requirements=["SIEM tools"], contract="internship", workload="100 %", city="Genève",
                 seniority="junior", languages=[{"language": "fr", "level": "required"}], posted="2026-11-20")


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


# ---------- rules, RSS, rejected offers kept, rescore ----------

@pytest.fixture
def user_rules(monkeypatch):
    monkeypatch.setattr(config, "KEPT_DOMAINS", ["Technology/IT", "Other"])
    monkeypatch.setattr(config, "DEALBREAKERS", [{"name": "senior level", "fact": "seniority", "in": ["senior"]}])
    monkeypatch.setattr(config, "BONUSES", [
        {"name": "security job", "fact": "category", "in": ["Cybersecurity SOC/incident response"], "points": 30}])


def test_rss_offers_go_through_the_same_triage_and_rules(user_rules, monkeypatch):
    from job_watch.offers import nodes
    from job_watch.offers.triage import Triage
    storage.save_offers([rss_offer("https://rss.example/known")])                        # already stored
    asked = []

    def fake_triage(offers, log=None, models=None):
        asked.extend(o.title for o in offers)
        return [Triage(domain="Technology/IT", category="Cybersecurity SOC/incident response", answered=True),
                Triage(domain="Finance, banking & accounting", answered=True),
                Triage(domain="Technology/IT", category="Software engineering", answered=True)][:len(offers)]

    monkeypatch.setattr(nodes, "triage_offers", fake_triage)
    state = {"offers": [rss_offer("https://rss.example/1", "SOC Analyst"), rss_offer("https://rss.example/2", "Accountant"),
                        rss_offer("https://rss.example/3", "Senior Developer"),
                        rss_offer("https://rss.example/known", "Known")]}
    triaged = nodes.triage_rss(state)
    assert asked == ["SOC Analyst", "Accountant", "Senior Developer"]                    # new RSS offers only
    judged = {o["title"]: (o["status"], o["score"], o["reasons"]) for o in nodes.apply_rules(triaged)["offers"]}
    assert judged["SOC Analyst"] == ("new", 30, ["security job (+30)"])
    assert judged["Accountant"][0] == "rejected" and judged["Accountant"][2][0].startswith("rejected: domain not kept")
    assert judged["Senior Developer"][0] == "rejected"                                    # seniority from the title


def test_rejected_offers_are_stored_with_their_reasons(user_rules):
    from job_watch.offers.nodes import apply_rules, save_results
    offers = apply_rules({"offers": [{**rss_offer("https://rss.example/9", "Senior SOC Analyst"),
                                      "domain": "Technology/IT"}]})["offers"]
    save_results({"offers": offers})
    conn = storage.connect()
    status, reasons = conn.execute("SELECT status, reasons FROM offers").fetchone()
    conn.close()
    assert status == "rejected" and json.loads(reasons) == ["rejected: senior level (seniority='senior')"]


def test_rescore_applies_new_rules_without_any_llm(user_rules, monkeypatch):
    from job_watch.offers.listed import connect as connect_listed, save_listed_offers
    from job_watch.offers.nodes import apply_rules, save_results
    from job_watch.offers.rescore import rescore
    from job_watch.offers.rules import kept, listing_rejections
    offer = {**rss_offer("https://bank.example/a", "SOC Analyst"), "key": "a", "source": "career_site",
             "domain": "Technology/IT", "category": "Cybersecurity SOC/incident response", "city": "Zurich",
             "languages": [{"language": "de", "level": "required"}]}
    save_results({"offers": apply_rules({"offers": [offer]})["offers"]})
    abroad = listed("b", "Security Engineer")
    abroad.location, abroad.domain = "Singapore", "Technology/IT"
    conn = connect_listed()
    abroad.rejected_by = listing_rejections(abroad, "Bank")                     # no "abroad" rule yet: kept
    save_listed_offers(conn, "Bank", [abroad], "2026-11-26", keep=kept)
    conn.close()

    monkeypatch.setattr(config, "DEALBREAKERS", [
        {"name": "German required", "fact": "languages_required", "contains": "de"},
        {"name": "abroad", "fact": "location", "is": "abroad"}])
    report = rescore()
    assert [(c.title, c.before, c.after) for c in report.offer_changes] == [("SOC Analyst", "kept, score 30", "rejected")]
    assert [(c.title, c.before, c.after) for c in report.listed_changes] == [("Security Engineer", "kept", "set aside")]
    conn = storage.connect()
    assert conn.execute("SELECT status FROM offers").fetchone() == ("rejected",)
    assert conn.execute("SELECT kept, reject_reason FROM listed_offers").fetchone() == (
        0, "rejected: abroad (location='abroad')")
    conn.close()


def test_rescore_dry_run_writes_nothing(user_rules, monkeypatch):
    from job_watch.offers.nodes import apply_rules, save_results
    from job_watch.offers.rescore import rescore
    save_results({"offers": apply_rules({"offers": [{**rss_offer("https://x.example/1", "SOC Analyst"),
                                                    "domain": "Technology/IT"}]})["offers"]})
    monkeypatch.setattr(config, "DEALBREAKERS", [{"name": "all", "fact": "domain", "is": "Technology/IT"}])
    assert len(rescore(write=False).offer_changes) == 1
    conn = storage.connect()
    assert conn.execute("SELECT status FROM offers").fetchone() == ("new",)
    conn.close()


def test_fact_columns_are_added_to_an_existing_offers_table():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("CREATE TABLE offers (company TEXT NOT NULL, key TEXT NOT NULL, link TEXT, title TEXT NOT NULL, "
                 "location TEXT, description TEXT, source TEXT, published TEXT, fetched TEXT, score INTEGER, "
                 "reasons TEXT, status TEXT, required_languages TEXT, PRIMARY KEY (company, key))")
    conn.execute("INSERT INTO offers (company, key, title, status) VALUES ('Bank', 'a', 'Analyst', 'new')")
    conn.commit()
    conn.close()
    conn = storage.connect()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}
    assert set(storage.FACT_COLUMNS) <= columns
    assert conn.execute("SELECT title FROM offers").fetchall() == [("Analyst",)]
    conn.close()

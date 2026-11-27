"""V1 pipeline with career sites: offers table, migration, node, conversion (no LLM, no browser).

Every database and registry is temporary: data/ is never touched.
"""
import json
import sqlite3

import pytest

from job_watch import config
from job_watch.list_agent.collect import CompanyCollection, DetailAnswers, DetailCollection
from job_watch.list_agent.extraction import CheckedOffer
from job_watch.offers import career_sites, storage
from job_watch.offers.criteria import Answer
from job_watch.offers.nodes import deduplicate
from job_watch.offers.scoring import Asked


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
              **asked([("c1", "yes", "SOC")], full_ad=True).model_dump()}
    other = {**career, "company": "Bank", "criteria_answers": None}                  # same key, other company
    assert storage.save_offers([career, other]) == [("Watchmaker", "ref:12"), ("Bank", "ref:12")]
    conn = storage.connect()
    conn.row_factory = sqlite3.Row
    stored = {r["company"]: storage.row_to_offer(r) for r in conn.execute("SELECT * FROM offers")}
    conn.close()
    assert stored["Watchmaker"]["criteria_answers"] == [{"id": "c1", "answer": "yes", "quote": "SOC"}]
    assert stored["Watchmaker"]["full_ad"] == 1 and stored["Watchmaker"]["criteria_model"] == "fake:model"
    assert stored["Bank"]["criteria_answers"] is None                                # every model failed


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


def asked(answers, full_ad=False, questions=None):
    from job_watch import config
    return Asked(criteria_questions=questions or config.SETTINGS.questions_id,
                 criteria_answers=[Answer(id=i, answer=a, quote=q) for i, a, q in answers],
                 criteria_model="fake:model", full_ad=full_ad)


def detail_answers(key):
    return DetailAnswers(key=key, asked=asked([("c1", "yes", "page text")], full_ad=True))


def test_to_offers_keeps_offers_without_detail():
    """The answers of the page win; an offer without detail keeps the answers on the listing."""
    a, b = listed("a", "Security Analyst", "https://bank.example/a"), listed("b", "SOC Analyst")
    a.asked = b.asked = asked([("c1", "yes", "Analyst")])
    found = career_sites.to_offers(collection("Bank", [a, b]),
                                   details("Bank", [detail_answers("a")], {"a": "Security Analyst page text"}),
                                   "2026-11-25")
    assert [(o["key"], o["description"], o["full_ad"], o["criteria_answers"][0]["quote"]) for o in found] == [
        ("a", "Security Analyst page text", True, "page text"), ("b", "", False, "Analyst")]
    assert found[0]["published"] == "" and found[1]["list_url"] == "https://bank.example/jobs"


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
                        lambda c, log=None: details(c.company, [detail_answers("a")], {"a": "text"}))
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


# ---------- criteria, RSS, rejected offers kept, rescore ----------

CRITERIA = [{"ask": "Is it a senior position?", "reject": True},          # c1
            {"ask": "Is it a SOC job?", "points": 30}]                     # c2


@pytest.fixture
def criteria(monkeypatch):
    """Settings of the tests, and a fake model: senior and SOC read from the title in the prompt."""
    from helpers import criteria_settings, fake_criteria

    def answer(prompt):
        title = next(line for line in prompt.splitlines() if line.startswith("Title: "))
        found = {}
        if "Senior" in title:
            found["c1"] = ("yes", "Senior")
        if "SOC" in title:
            found["c2"] = ("yes", "SOC")
        return found
    return fake_criteria(monkeypatch, criteria_settings(CRITERIA), answer)


def test_rss_offers_go_through_the_same_triage_and_criteria(criteria, monkeypatch):
    from job_watch.offers import nodes
    from job_watch.offers.triage import Triage
    storage.save_offers([rss_offer("https://rss.example/known")])                        # already stored
    asked_titles = []

    def fake_triage(offers, log=None, models=None):
        asked_titles.extend(o.title for o in offers)
        return [Triage(domain="Technology/IT", answered=True), Triage(domain="Finance, banking & accounting", answered=True),
                Triage(domain="Technology/IT", answered=True)][:len(offers)]

    monkeypatch.setattr(nodes, "triage_offers", fake_triage)
    state = {"offers": [rss_offer("https://rss.example/1", "SOC Analyst"), rss_offer("https://rss.example/2", "Accountant"),
                        rss_offer("https://rss.example/3", "Senior Developer"),
                        rss_offer("https://rss.example/known", "Known")]}
    triaged = nodes.triage_rss(state)
    assert asked_titles == ["SOC Analyst", "Accountant", "Senior Developer"]             # new RSS offers only
    judged = {o["title"]: (o["status"], o["score"], o["reasons"]) for o in nodes.score_offers(triaged)["offers"]}
    assert judged["SOC Analyst"] == ("new", 30, ["Is it a SOC job? (+30): 'SOC'"])
    assert judged["Accountant"] == ("rejected", 0, ["rejected: domain not kept | 'Finance, banking & accounting'"])
    assert judged["Senior Developer"] == ("rejected", 0, ["rejected: Is it a senior position? | 'Senior'"])
    # One LLM call per new RSS offer whose domain is kept; never for the known one or the accountant
    assert [p.split("Title: ")[1].split("\n")[0] for p in criteria.prompts] == ["SOC Analyst", "Senior Developer"]
    assert all("<ad>\ntext\n</ad>" in p for p in criteria.prompts)                      # the feed description


def test_rejected_offers_are_stored_with_their_reasons_and_answers(criteria):
    from job_watch.offers.nodes import save_results, score_offers
    offers = score_offers({"offers": [{**rss_offer("https://rss.example/9", "Senior SOC Analyst"),
                                       "domain": "Technology/IT"}]})["offers"]
    save_results({"offers": offers})
    conn = storage.connect()
    status, reasons, model, full_ad = conn.execute("SELECT status, reasons, criteria_model, full_ad FROM offers").fetchone()
    conn.close()
    assert status == "rejected" and json.loads(reasons) == ["rejected: Is it a senior position? | 'Senior'"]
    assert model == "" and full_ad == 0             # the fake model is not counted by llm.py; RSS: not a full ad


def test_rescore_applies_new_settings_without_any_llm(criteria, monkeypatch):
    from helpers import criteria_settings
    from job_watch import config
    from job_watch.list_agent.collect import keep
    from job_watch.offers.listed import connect as connect_listed, save_listed_offers
    from job_watch.offers.nodes import save_results, score_offers
    from job_watch.offers.rescore import rescore
    from job_watch.offers.scoring import screen_listed
    offer = {**rss_offer("https://bank.example/a", "SOC Analyst"), "domain": "Technology/IT"}
    save_results({"offers": score_offers({"offers": [offer]})["offers"]})
    aside = listed("b", "Senior SOC Engineer")
    aside.domain = "Technology/IT"
    screen_listed(aside, "Bank")                                                 # set aside: senior
    conn = connect_listed()
    save_listed_offers(conn, "Bank", [aside], "2026-11-26", keep=keep)
    conn.close()
    calls = len(criteria.prompts)

    # Same questions, other points and no reject: the stored answers are checked and scored again
    monkeypatch.setattr(config, "SETTINGS", criteria_settings([{"ask": "Is it a senior position?", "points": -10},
                                                               {"ask": "Is it a SOC job?", "points": 5}]))
    assert config.SETTINGS.questions_id == criteria_settings(CRITERIA).questions_id
    report = rescore()
    assert len(criteria.prompts) == calls                                        # no LLM call
    assert [(c.title, c.before, c.after) for c in report.offer_changes] == [("SOC Analyst", "kept, score 30",
                                                                             "kept, score 5")]
    assert [(c.title, c.before, c.after) for c in report.listed_changes] == [("Senior SOC Engineer", "set aside",
                                                                              "kept")]
    assert [c.title for c in report.kept_without_detail] == ["Senior SOC Engineer"]
    conn = storage.connect()
    assert conn.execute("SELECT score FROM offers").fetchone() == (5,)
    assert conn.execute("SELECT kept, reject_reason FROM listed_offers").fetchone() == (1, "")
    conn.close()

    # Other questions: the answers are not used, the stored values stay
    monkeypatch.setattr(config, "SETTINGS", criteria_settings([{"ask": "Is it remote?", "points": 50}]))
    report = rescore()
    assert report.offers_not_rescored == 1 and report.listed_not_rescored == 1 and not report.offer_changes


def test_rescore_asks_again_only_what_has_no_answers_to_the_current_questions(criteria, monkeypatch):
    from helpers import criteria_settings
    from job_watch import config
    from job_watch.list_agent.collect import keep
    from job_watch.offers.listed import connect as connect_listed, save_listed_offers
    from job_watch.offers.nodes import save_results, score_offers
    from job_watch.offers.rescore import rescore, to_ask
    from job_watch.offers.scoring import screen_listed
    save_results({"offers": score_offers({"offers": [{**rss_offer("https://x.example/1", "SOC Analyst"),
                                                     "domain": "Technology/IT"}]})["offers"]})
    old = listed("b", "Senior SOC Engineer")
    old.domain = "Technology/IT"
    screen_listed(old, "Bank")
    hr = listed("c", "HR Partner")
    hr.domain, hr.rejected_by = "HR, legal & administration", ["rejected: domain not kept | 'HR'"]
    conn = connect_listed()
    save_listed_offers(conn, "Bank", [old, hr], "2026-11-27", keep=keep)
    conn.close()
    assert to_ask() == (0, 0)

    # A question added: every answer is outdated; the domain set aside is never asked
    monkeypatch.setattr(config, "SETTINGS", criteria_settings([*CRITERIA, {"ask": "Is it remote?", "points": 5}]))
    criteria.settings = config.SETTINGS
    assert to_ask() == (1, 1)
    calls = len(criteria.prompts)
    with pytest.raises(ValueError):
        rescore(write=False, ask_missing=True)                                  # asking always writes
    report = rescore(ask_missing=True)
    assert (report.offers_asked, report.listed_asked) == (1, 1) and len(criteria.prompts) == calls + 2
    assert report.offers_not_rescored == report.listed_not_rescored == 0
    assert to_ask() == (0, 0)                                                   # answers stored
    assert rescore(ask_missing=True).offers_asked == 0 and len(criteria.prompts) == calls + 2


def test_rescore_dry_run_writes_nothing(criteria, monkeypatch):
    from helpers import criteria_settings
    from job_watch import config
    from job_watch.offers.nodes import save_results, score_offers
    from job_watch.offers.rescore import rescore
    save_results({"offers": score_offers({"offers": [{**rss_offer("https://x.example/1", "SOC Analyst"),
                                                     "domain": "Technology/IT"}]})["offers"]})
    monkeypatch.setattr(config, "SETTINGS", criteria_settings(CRITERIA, kept_domains=["Other"]))
    assert len(rescore(write=False).offer_changes) == 1                          # domain no longer kept
    conn = storage.connect()
    assert conn.execute("SELECT status FROM offers").fetchone() == ("new",)
    conn.close()


def test_new_columns_are_added_and_the_fact_sheet_columns_dropped():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("CREATE TABLE offers (company TEXT NOT NULL, key TEXT NOT NULL, link TEXT, title TEXT NOT NULL, "
                 "location TEXT, description TEXT, source TEXT, published TEXT, fetched TEXT, score INTEGER, "
                 "reasons TEXT, status TEXT, seniority TEXT, contract TEXT, PRIMARY KEY (company, key))")
    conn.execute("INSERT INTO offers (company, key, title, source, published, status, seniority) "
                 "VALUES ('Bank', 'a', 'Analyst', 'career_site', '2026-02-27', 'new', 'junior')")
    conn.execute("INSERT INTO offers (company, key, title, source, published, status) "
                 "VALUES ('Bank', 'url:x', 'Dev', 'swissdevjobs', '2026-11-20', 'new')")
    conn.commit()
    conn.close()
    conn = storage.connect()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}
    assert set(storage.FACT_COLUMNS) <= columns and not columns & {"seniority", "contract"}
    # The career-site date came from the fact sheet (never checked in the page): emptied; the feed date stays
    assert conn.execute("SELECT title, published FROM offers ORDER BY title").fetchall() == [
        ("Analyst", ""), ("Dev", "2026-11-20")]
    conn.close()


def test_one_progress_line_per_offer_asked(criteria, capsys):
    from job_watch.offers.nodes import score_offers
    offers = [{**rss_offer(f"https://rss.example/{n}", title), "domain": "Technology/IT"}
              for n, title in enumerate(["SOC Analyst", "Developer"])]
    score_offers({"offers": offers})
    out = capsys.readouterr().out
    assert "criteria 1/2: 'SOC Analyst' every model failed" not in out          # the fake model answers
    assert "criteria 1/2: 'SOC Analyst'" in out and "criteria 2/2: 'Developer'" in out and " s\n" in out


@pytest.fixture
def only_local(monkeypatch):
    """Every cloud model skipped for the run: LOCAL_ONLY_MAX_CRITERIA offers are still asked."""
    from job_watch.offers import scoring
    monkeypatch.setattr(scoring, "only_local_left", lambda: True)
    monkeypatch.setattr(scoring, "_local_only", {"asked": 0})
    monkeypatch.setattr(config, "LOCAL_ONLY_MAX_CRITERIA", 1)


def test_rss_offers_are_deferred_when_only_local_models_are_left(criteria, only_local, capsys):
    from job_watch.offers.nodes import save_results, score_offers
    offers = [{**rss_offer(f"https://rss.example/{n}", title), "domain": "Technology/IT"}
              for n, title in enumerate(["SOC Analyst", "Developer", "Tester"])]
    scored = score_offers({"offers": offers})["offers"]
    assert [o["title"] for o in scored] == ["SOC Analyst"] and len(criteria.prompts) == 1
    assert "1 RSS offers asked, 2 deferred to the next run" in capsys.readouterr().out
    save_results({"offers": scored})
    assert storage.known_offers() == {("Bank", "url:https://rss.example/0")}         # the others stay new


def test_listed_offers_deferred_are_not_saved(criteria, only_local):
    from job_watch.list_agent.collect import save_collection
    from job_watch.offers.listed import connect as connect_listed, known_keys
    from job_watch.offers.scoring import screen_listed
    first, second = listed("a", "SOC Analyst"), listed("b", "Developer")
    first.domain = second.domain = "Technology/IT"
    assert screen_listed(first, "Bank") and not screen_listed(second, "Bank")        # second: deferred
    found = collection("Bank", [first, second])
    found.deferred = ["b"]
    conn = connect_listed()
    save_collection(conn, found)
    assert known_keys(conn, "Bank") == {"a"}
    conn.close()


def test_the_salary_line_of_the_feed_is_not_part_of_the_description():
    """The feed starts every description with its own salary estimate: never the employer's salary."""
    from job_watch.offers.nodes import without_board_salary
    feed = "Salary: CHF 135'000 - 150'000 per year\nRequirements:\nPython"
    assert without_board_salary(feed) == "Requirements:\nPython"
    employer = "About us\nSalary: CHF 120'000 per year\nPython"            # written in the ad itself
    assert without_board_salary(employer) == employer
    assert without_board_salary("") == ""

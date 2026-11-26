"""Adding a known job list to the registry: robots.txt and page judge are faked (no network, no LLM)."""
from datetime import date

import pytest

from job_watch.judges.page_judge import PageCheck
from job_watch.registry import add
from job_watch.web import access

URL = "https://www.careers.example.com/jobs"


@pytest.fixture
def fakes(monkeypatch):
    state = {"robots": access.ALLOWED, "page": {"url": URL, "text": "Open positions", "links": []},
             "answer": PageCheck(page_type="job_list", owner_matches="yes", jobs_link="", reason="Lists 40 offers."),
             "judged": 0}
    monkeypatch.setattr(add.web, "robots_status", lambda url: state["robots"])
    monkeypatch.setattr(add.web, "can_fetch", lambda url: state["robots"] == access.ALLOWED)
    monkeypatch.setattr(add, "render_page", lambda url: state["page"])

    def judge(company, page):
        state["judged"] += 1
        return state["answer"]
    monkeypatch.setattr(add, "judge_page_with_retry", judge)
    return state


def test_a_confirmed_job_list_gives_an_ok_entry(fakes):
    result = add.check_known_list("Example", URL, {}, today=date(2026, 11, 26))
    assert result.added and result.entry["status"] == "ok" and result.entry["jobs_url"] == URL
    assert result.entry["verified"] == {"date": "2026-11-26", "trail": [
        {"url": URL, "page_type": "job_list", "owner": "yes", "reason": "Lists 40 offers."}]}


@pytest.mark.parametrize("change, reason", [
    ({"robots": access.DISALLOWED}, "forbidden by robots.txt"),
    ({"robots": access.ERROR}, "robots.txt unreadable"),
    ({"page": None}, "page failed to load"),
    ({"answer": None}, "LLM unavailable"),
    ({"answer": PageCheck(page_type="overview", owner_matches="yes", jobs_link="", reason="Values.")}, "'overview'"),
    ({"answer": PageCheck(page_type="job_list", owner_matches="unknown", jobs_link="", reason="?")},
     "cannot confirm the owner (unknown)"),
    ({"answer": PageCheck(page_type="job_list", owner_matches="no", jobs_link="", reason="Other firm.")},
     "cannot confirm the owner (no)"),
])
def test_refused_with_the_reason(fakes, change, reason):
    fakes.update(change)
    result = add.check_known_list("Example", URL, {})
    assert not result.added and result.entry is None and reason in result.reason


def test_robots_is_checked_before_the_page_is_judged(fakes):
    fakes["robots"] = access.DISALLOWED
    add.check_known_list("Example", URL, {})
    assert fakes["judged"] == 0


def test_an_existing_company_is_never_overwritten(fakes):
    result = add.check_known_list("example", URL, {"Example": {"status": "not_found", "jobs_url": None}})
    assert not result.added and "already in the registry" in result.reason and fakes["judged"] == 0


def test_the_script_writes_only_an_accepted_entry(fakes, monkeypatch, capsys):
    import json
    from job_watch import config
    from scripts import add_registry_entry
    monkeypatch.setattr("sys.argv", ["add_registry_entry", "Example", URL])
    add_registry_entry.main()
    assert json.loads(config.REGISTRY_PATH.read_text())["Example"]["jobs_url"] == URL
    assert "ADDED" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["add_registry_entry", "Other", URL])
    fakes["robots"] = access.DISALLOWED
    with pytest.raises(SystemExit):
        add_registry_entry.main()
    assert "Other" not in json.loads(config.REGISTRY_PATH.read_text())
    assert "REFUSED  Other: forbidden" in capsys.readouterr().out

"""Registry check of one entry again (verify_registry --company): page judge faked (no network, no LLM)."""
from job_watch.registry import verify

ENTRY = {"status": "ok", "jobs_url": "https://other-bordier.example/jobs", "aliases": [],
         "candidates": [{"url": "https://www.bordier.ch/careers", "title": "Bordier careers"}],
         "verified": {"date": "2026-11-01", "trail": [{"url": "https://other-bordier.example/jobs"},
                                                     {"url": "https://www.bordier.ch/careers"}]}}


def test_a_verified_entry_is_judged_again_only_when_forced(monkeypatch):
    judged = []

    def fake_verify(company, url):
        judged.append(url)
        if "other-bordier" in url:
            return "not_found", None, [{"url": url, "page_type": "job_list", "owner": "no", "reason": "French homonym"}]
        return "ok", url, [{"url": url, "page_type": "job_list", "owner": "yes", "reason": "Geneva bank"}]
    monkeypatch.setattr(verify, "verify", fake_verify)
    monkeypatch.setattr(verify, "domain_matches", lambda url, names: "bordier" in url)
    assert verify.check_entry("Bordier", ENTRY)[0] == "not_found" and judged == []      # already verified
    outcome, url, trail, from_candidates, _ = verify.check_entry("Bordier", ENTRY, force=True)
    assert judged == ["https://other-bordier.example/jobs", "https://www.bordier.ch/careers"]
    assert (outcome, url, from_candidates) == ("ok", "https://www.bordier.ch/careers", True)

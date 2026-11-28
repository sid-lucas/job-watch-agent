"""scripts/show_offers.py: best kept offers of the whole database (no LLM, read only)."""
from job_watch import config
from job_watch.offers import storage


def _offer(key, company, score, fetched, status="new", source="career_site", link="https://x.ch/1"):
    return {"company": company, "key": key, "link": link, "title": f"Job {key}", "location": "Geneva",
            "source": source, "fetched": fetched, "score": score, "status": status,
            "reasons": [f"SOC (+{score}): 'SOC'"]}


def test_kept_offers_best_score_then_most_recently_seen_with_filters(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "offers.db")
    storage.save_offers([
        _offer("a", "Bank", 30, "2026-11-01"), _offer("b", "Bank", 30, "2026-11-20"),
        _offer("c", "Watch", 50, "2026-10-01", source="swissdevjobs"), _offer("d", "Bank", 10, "2026-11-25"),
        _offer("e", "Bank", 90, "2026-11-25", status="rejected")])
    assert [o["key"] for o in storage.kept_offers()] == ["c", "b", "a", "d"]
    assert [o["key"] for o in storage.kept_offers(company="bank", min_score=20)] == ["b", "a"]
    assert [o["key"] for o in storage.kept_offers(source="swissdevjobs")] == ["c"]
    assert storage.kept_offers()[0]["reasons"] == ["SOC (+50): 'SOC'"]


def test_missing_database_is_not_created(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "none.db")
    assert storage.kept_offers() == []
    assert not (tmp_path / "none.db").exists()


def test_script_prints_the_top_in_the_main_format(tmp_path, monkeypatch, capsys):
    from scripts import show_offers
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "offers.db")
    storage.save_offers([_offer("a", "Bank", 30, "2026-11-01"), _offer("b", "Bank", 40, "2026-11-02", link="")])
    show_offers.main(["--top", "1", "--min-score", "0"])
    out = capsys.readouterr().out
    assert out.startswith("2 kept offers with score >= 0, the best 1:\n\n  40  Job b @ Bank  [career_site]\n"
                          "      SOC (+40): 'SOC'\n      Location: Geneva\n            List:   -")
    assert "Job a" not in out and out.endswith("\n... and 1 more (--top)\n")


def test_by_match_sorts_by_match_percent_and_shows_it(tmp_path, monkeypatch, capsys):
    from job_watch.matching import store
    from scripts import show_offers
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "offers.db")
    monkeypatch.setattr(config, "MATCH_DB_PATH", tmp_path / "personal" / "matching.db")
    storage.save_offers([_offer("a", "Bank", 50, "2026-11-01"), _offer("b", "Bank", 40, "2026-11-02"),
                         _offer("c", "Bank", 30, "2026-11-03")])
    store.save("Bank", "b", {}, "m", "p", 80.0, [])
    store.save("Bank", "c", {}, "m", "p", 60.0, ["German B2: missing"])
    show_offers.main(["--by-match", "--min-score", "0"])
    out = capsys.readouterr().out
    assert out.index("Job b") < out.index("Job c") < out.index("Job a")
    assert "Match: 80%" in out and "Match: 60% | BLOCKING: German B2: missing" in out and "Match: not matched" in out


def test_without_by_match_no_matching_database_is_opened(tmp_path, monkeypatch, capsys):
    from scripts import show_offers
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "offers.db")
    monkeypatch.setattr(config, "MATCH_DB_PATH", tmp_path / "personal" / "matching.db")
    storage.save_offers([_offer("a", "Bank", 50, "2026-11-01")])
    show_offers.main([])
    assert "Match" not in capsys.readouterr().out and not (tmp_path / "personal").exists()

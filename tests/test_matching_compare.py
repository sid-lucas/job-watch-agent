"""Matching brick 2: requirements compared with the fictitious profile (tests/fixtures/profile_example.md).

No LLM: fake local models. Rules of the code (quotes, levels, options, years), storage in
matching.db only, and the guarantee that the profile and the matching answers never reach a cloud model.
"""
import ast
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessageChunk
from langchain_core.runnables import RunnableLambda

from job_watch import config, llm
from job_watch.matching import compare, store
from job_watch.matching.profile import level_of, read_profile, total_years
from job_watch.matching.requirements import Requirement, Requirements

PROFILE = read_profile()            # the fictitious profile (conftest)
ROOT = config.BASE_DIR


def req(label, kind="must", category="skill", options=(), min_years=None, quote="the ad"):
    return Requirement(quote=quote, kind=kind, category=category, label=label, options=list(options),
                       min_years=min_years, level="")


def answer(verdict, quote="", reason="r"):
    return {"reason": reason, "profile_quote": quote, "verdict": verdict}


# ---------- reading the profile in code ----------

def test_level_of_the_line_that_holds_the_quote():
    assert level_of(PROFILE, "Splunk").level == "Pro"
    assert level_of(PROFILE, "réponse à incident").level == "Labo"          # its own tag, not the first one
    assert level_of(PROFILE, "forensic [Cours]").level == "Cours"
    assert level_of(PROFILE, "Azure").level == "En cours"
    java = level_of(PROFILE, "Java [Cours] (ancien)")
    assert (java.level, java.old) == ("Cours", True)
    windows = level_of(PROFILE, "Support Windows et Active Directory")
    assert (windows.level, windows.old, windows.text()) == ("Pro", True, "[Pro] (ancien)")
    assert level_of(PROFILE, "Python [Pro]").old is False
    several = level_of(PROFILE, "Python [Pro], Bash [Projet], Java [Cours] (ancien)")   # "(ancien)" is Java's
    assert (several.level, several.old) == ("Pro", False)
    assert level_of(PROFILE, "Haute école fictive de Lausanne").level is None   # table line: no level


def test_total_experience_from_the_summary():
    assert total_years(PROFILE) == 2
    assert total_years("## 1. Formation\nExpérience totale : 9 ans") is None     # not in the summary


# ---------- rules of the code ----------

def test_covered_without_a_quote_of_the_profile_becomes_unknown_missing_needs_none():
    results = compare.judge_all([req("Kubernetes"), req("Rust"), req("Python")], {
        "r1": answer("covered", "Kubernetes [Pro]"),          # invented
        "r2": answer("missing"),
        "r3": answer("covered", "Python [Pro]")}, PROFILE)
    assert [m.verdict for m in results] == ["unknown", "missing", "covered"]
    assert results[0].notes == ["quote not in the profile: covered -> unknown"]
    assert results[2].level.level == "Pro" and results[2].profile_quote == "Python [Pro]"


def test_weak_or_old_levels_cap_a_must_requirement_at_partial():
    results = compare.judge_all([req("Java"), req("Java", kind="nice"), req("Azure"), req("Active Directory")], {
        "r1": answer("covered", "Java [Cours] (ancien)"), "r2": answer("covered", "Java [Cours] (ancien)"),
        "r3": answer("covered", "Azure [En cours]"),
        "r4": answer("covered", "Support Windows et Active Directory [Pro] (ancien)")}, PROFILE)
    assert [m.verdict for m in results] == ["partial", "covered", "partial", "partial"]
    assert results[0].notes == ["level [Cours] (ancien): covered -> partial"]


def test_a_requirement_with_options_is_covered_when_one_option_is():
    requirement = req("SIEM", category="tool", options=["QRadar", "Splunk", "Sentinel"])
    assert compare.answer_ids([req("Python"), requirement]) == [["r1"], ["r2_o1", "r2_o2", "r2_o3"]]
    [result] = compare.judge_all([requirement], {"r1_o1": answer("missing"), "r1_o2": answer("covered", "Splunk [Pro]"),
                                                 "r1_o3": answer("unknown")}, PROFILE)
    assert (result.verdict, result.option) == ("covered", "Splunk")


def test_min_years_above_the_total_experience_caps_at_partial():
    results = compare.judge_all(
        [req("SOC experience", category="experience", min_years=3),
         req("SOC experience", category="experience", min_years=1)],
        {"r1": answer("covered", "Analyste SOC junior"), "r2": answer("covered", "Analyste SOC junior")}, PROFILE)
    assert [m.verdict for m in results] == ["partial", "covered"]
    assert results[0].notes == ["total experience 2 years < 3: covered -> partial"]


def test_an_answer_outside_the_schema_is_unknown():
    [result] = compare.judge_all([req("Python")], {"r1": {"verdict": "yes"}}, PROFILE)
    assert result.verdict == "unknown"
    [result] = compare.judge_all([req("Python")], {}, PROFILE)
    assert result.verdict == "unknown"


def test_the_schema_has_one_required_field_per_requirement_or_option():
    schema = compare.schema_for([req("Python"), req("Cloud", options=["AWS", "Azure"])]).model_json_schema()
    assert schema["required"] == ["r1", "r2_o1", "r2_o2"]


# ---------- local calls, storage ----------

class LocalModel:
    """A fake local model answering every id of the schema it receives (or reasoning too long)."""

    def __init__(self, verdicts=None, too_long_with_reasoning=False):
        self.verdicts, self.too_long = verdicts or {}, too_long_with_reasoning
        self.calls = []

    def __call__(self, messages, max_tokens, timeout, think=False, schema=None, chain=None):
        self.calls.append({"messages": messages, "think": think, "chain": chain})
        if self.too_long and think:
            raise llm.LocalCallFailed("too long")
        ids = schema.model_json_schema()["required"]
        return json.dumps({i: self.verdicts.get(i, answer("covered", "Python [Pro]")) for i in ids}), "ollama:fake"


OFFER = {"company": "Bank", "key": "a"}


def test_answers_are_stored_in_matching_db_and_reused(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MATCH_DB_PATH", tmp_path / "personal" / "matching.db")
    model = LocalModel()
    monkeypatch.setattr(compare, "local_call", model)
    requirements = [req("Python")]
    first = compare.match_offer(OFFER, requirements, PROFILE)
    assert first.results[0].verdict == "covered" and not first.reused and len(model.calls) == 1
    assert model.calls[0]["think"] is config.MATCH_THINK and model.calls[0]["chain"] is None   # MATCH_CHAIN
    assert store.stored("Bank", "a")["model"] == "ollama:fake"
    assert compare.match_offer(OFFER, requirements, PROFILE).reused and len(model.calls) == 1
    compare.match_offer(OFFER, requirements, PROFILE, refresh=True)
    assert len(model.calls) == 2
    compare.match_offer(OFFER, requirements, PROFILE + "\n- Rust [Projet]")       # profile changed
    assert len(model.calls) == 3
    compare.match_offer(OFFER, [req("Python"), req("Go")], PROFILE + "\n- Rust [Projet]")   # requirements changed
    assert len(model.calls) == 4


def test_reasoning_too_long_is_replaced_by_one_call_without_reasoning(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MATCH_DB_PATH", tmp_path / "matching.db")
    monkeypatch.setattr(config, "MATCH_THINK", True)
    model = LocalModel(too_long_with_reasoning=True)
    monkeypatch.setattr(compare, "local_call", model)
    assert compare.match_offer(OFFER, [req("Python")], PROFILE).results[0].verdict == "covered"
    assert [c["think"] for c in model.calls] == [True, False]


def test_a_timeout_fails_the_offer_and_nothing_is_stored(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MATCH_DB_PATH", tmp_path / "matching.db")
    def timeout(*args, **kwargs):
        raise llm.LocalCallFailed("timeout")
    monkeypatch.setattr(compare, "local_call", timeout)
    assert compare.match_offer(OFFER, [req("Python")], PROFILE).failure == "timeout"
    assert store.stored("Bank", "a") is None


def test_matching_db_is_refused_with_a_cloud_model_in_the_match_chain(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MATCH_DB_PATH", tmp_path / "matching.db")
    monkeypatch.setattr(config, "MATCH_CHAIN", [("gemini", "g", False), ("ollama", "qwen3:8b", True)])
    with pytest.raises(SystemExit, match="only hold local models"):
        store.stored("Bank", "a")
    assert not (tmp_path / "matching.db").exists()


# ---------- the profile and the matching never reach a cloud model ----------

class Clients:
    """Fake clients for every provider: cloud ones record their prompts and extract requirements,
    local ones answer the comparison as a stream."""

    def __init__(self):
        self.cloud_prompts, self.local_prompts = [], []

    def __call__(self, provider, model, think=None, max_tokens=None, timeout=None):
        if provider not in config.LOCAL_PROVIDERS:
            return self._cloud()
        return self._local()

    def _cloud(self):
        clients = self
        class Cloud:
            def with_structured_output(self, schema):
                def reply(messages):
                    clients.cloud_prompts.append(str(messages))
                    return Requirements(requirements=[Requirement(
                        quote="Strong Python skills", kind="must", category="skill", label="Python", options=[],
                        min_years=None, level="")])
                return RunnableLambda(reply)
        return Cloud()

    def _local(self):
        clients = self
        class Local:
            def stream(self, messages, **options):
                clients.local_prompts.append(str(messages))
                ids = options["format"]["required"]
                yield AIMessageChunk(content=json.dumps({i: answer("covered", "Python [Pro]") for i in ids}),
                                     response_metadata={"done_reason": "stop"})
        return Local()


def test_the_profile_and_the_matching_answers_never_go_to_a_cloud_prompt(monkeypatch, tmp_path, capsys):
    from job_watch.offers import storage
    from scripts import match_offers
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "offers.db")
    monkeypatch.setattr(config, "MATCH_DB_PATH", tmp_path / "personal" / "matching.db")
    monkeypatch.setattr(config, "MATCH_CHAIN", [("ollama", "qwen3:8b", True)])
    monkeypatch.setattr(config, "REQUIREMENTS_CHAIN", [("gemini", "g", True), ("ollama", "qwen3:8b", True)])
    clients = Clients()
    monkeypatch.setattr(llm, "_client", clients)
    storage.save_offers([{"company": "Bank", "key": "a", "link": "", "title": "Dev", "location": "Geneva",
                          "description": "Strong Python skills. German is a plus.", "source": "career_site",
                          "score": 90, "status": "new", "reasons": []}])
    for run in range(2):                                  # extracted and compared, then both reused
        match_offers.main(["--top", "1"] + (["--refresh"] if run else []))
    assert "covered" in capsys.readouterr().out
    assert len(clients.cloud_prompts) == 1 and len(clients.local_prompts) == 2
    stored_answers = json.dumps(store.stored("Bank", "a")["answers"], ensure_ascii=False)
    profile_lines = [line.strip() for line in PROFILE.splitlines() if len(line.strip()) > 12]
    for prompt in clients.cloud_prompts:
        assert not any(line in prompt for line in profile_lines)
        assert "Python [Pro]" not in prompt and stored_answers not in prompt
    assert any("Banque Fictive SA" in prompt for prompt in clients.local_prompts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {f"{node.module}.{a.name}" for a in node.names} | {node.module or ""}
        elif isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
    return names


def test_only_the_matching_package_opens_matching_db_and_reads_the_profile():
    personal = ("MATCH_DB_PATH", "PROFILE_PATH")
    for path in [*ROOT.glob("job_watch/**/*.py"), *ROOT.glob("scripts/*.py"), *ROOT.glob("evals/*.py"), ROOT / "main.py"]:
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if relative.startswith("job_watch/matching/") or relative == "job_watch/config.py":
            continue
        assert not any(name in text for name in personal), relative
        allowed = relative == "scripts/match_offers.py"
        assert allowed or not any(i.startswith(("job_watch.matching.store", "job_watch.matching.compare",
                                                "job_watch.matching.profile")) for i in _imports(path)), relative


def test_the_modules_that_read_personal_data_have_no_cloud_access():
    cloud = {"job_watch.llm.structured_llm", "job_watch.llm.tool_llm", "job_watch.llm.call_with_retry",
             "job_watch.llm._client", "job_watch.llm.llm_chain"}
    for name in ("compare", "store", "profile"):
        imports = _imports(ROOT / "job_watch" / "matching" / f"{name}.py")
        assert not imports & cloud, name

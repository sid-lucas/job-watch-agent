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
from job_watch.matching.profile import (Level, language_level, language_name, line_level, numbered, profile_lines,
                                        read_profile, section_key, total_years)
from job_watch.matching.requirements import Requirement, Requirements

PROFILE = read_profile()            # the fictitious profile (conftest)
ROOT = config.BASE_DIR


def req(label, kind="must", category="skill", options=(), min_years=None, quote="the ad"):
    return Requirement(quote=quote, kind=kind, category=category, label=label, options=list(options),
                       min_years=min_years, level="")


def answer(verdict, lines=(), reason="r"):
    return {"reason": reason, "profile_lines": list(lines), "verdict": verdict}


def judge(requirements, answers):
    return compare.judge_all(requirements, answers, PROFILE)


# ---------- reading the profile in code ----------

def test_numbered_lines_with_their_section():
    lines = {line.id: line for line in profile_lines(PROFILE)}
    assert (lines["L1"].section, lines["L1"].text) == ("0. Résumé", "- Expérience totale : 2 ans (dont 1 an en sécurité)")
    assert lines["L29"].section == "6. Langues" and "Anglais" in lines["L29"].text
    assert not any(line.text.startswith("## ") or set(line.text) <= set("|-: ") for line in lines.values())
    assert numbered(list(lines.values())).splitlines()[10] == ("L11 [2. Expérience professionnelle] - Tri des alertes "
                                                              "dans le SIEM [Pro] : Splunk [Pro]")
    assert section_key("0. Résumé") == "resume" and section_key("2. Expérience professionnelle") == "experience professionnelle"


def test_level_of_a_line_for_a_requirement():
    assert line_level("- Scripts d'automatisation en Python [Pro]", ["Python"]).level == "Pro"
    several = "- Développement : Python [Pro], Bash [Projet], Java [Cours] (ancien)"
    assert line_level(several, ["Python"]) == Level(level="Pro", old=False)       # "(ancien)" is Java's
    assert line_level(several, ["Java"]) == Level(level="Cours", old=True)
    assert line_level(several, ["Kubernetes"]) == Level()                        # several levels, none named
    assert line_level("- Support Windows et Active Directory [Pro] (ancien)", ["Linux"]) == Level(level="Pro", old=True)
    assert line_level("- Sécurité défensive : SIEM [Pro], réponse à incident [Labo]", ["Incident response",
                                                                                    "réponse incident"]).level == "Labo"
    assert line_level("| Bachelor en informatique | Haute école |", ["Bachelor"]) == Level()


def test_language_levels():
    assert [language_level(t) for t in ("C1", "fluent", "courant", "notions", "débutant", "B2")] == [5, 5, 5, 2, 1, 4]
    assert language_level("| Français | Langue maternelle | |") == 7
    assert language_level("| Anglais | C1 | Certificat fictif C1 (2024) |") == 5
    assert language_level("| Allemand | A2 | Cours de l'école |") == 2
    assert language_level("") is None and language_name(7) == "native" and language_name(4) == "B2"


def test_total_experience_from_the_summary():
    assert total_years(PROFILE) == 2
    assert total_years("## 1. Formation\n- Expérience totale : 9 ans") is None      # not in the summary


# ---------- rules of the code ----------

def test_the_code_reads_the_lines_the_model_names():
    results = judge([req("Kubernetes"), req("Rust"), req("Python")], {
        "r1": answer("covered", ["L99"]),                     # no such line
        "r2": answer("missing"),
        "r3": answer("covered", ["L13", "L25"])})
    assert [m.verdict for m in results] == ["unknown", "missing", "covered"]
    assert results[0].notes == ["line ids not in the profile: L99", "no line of the profile: unknown"]
    assert results[2].line.id == "L13" and results[2].level.level == "Pro"
    [result] = judge([req("Python")], {"r1": answer("covered", ["l13"])})          # case of the id ignored
    assert result.line.id == "L13"


def test_each_category_accepts_only_its_sections():
    results = judge([req("French", category="language"), req("Bachelor", category="education"),
                     req("SOC experience", category="experience", min_years=1),
                     req("Model benchmarking"), req("Security+", category="certification")], {
        "r1": answer("covered", ["L3"]),                      # "nationalité suisse" does not prove French
        "r2": answer("covered", ["L8"]),
        "r3": answer("covered", ["L20"]),                     # a CTF is not years of work
        "r4": answer("covered", ["L22"]),                     # other categories: any section
        "r5": answer("covered", ["L2"])})
    assert [m.verdict for m in results] == ["unknown", "covered", "unknown", "covered", "covered"]
    assert results[0].notes == ["L3 (0. Résumé) cannot prove a language: covered -> unknown"]
    [kept] = judge([req("SOC experience", category="experience", min_years=1)], {"r1": answer("covered", ["L20", "L10"])})
    assert (kept.verdict, kept.line.id) == ("covered", "L10")                # the accepted line is used


def test_languages_are_compared_by_level():
    def language(label, level, line):
        [result] = judge([req(label, category="language") .model_copy(update={"level": level})],
                         {"r1": answer("covered", [line])})
        return result.verdict
    assert language("English", "C1", "L29") == "covered"
    assert language("English", "C2", "L29") == "partial"                   # one level below
    assert language("German", "B2", "L30") == "missing"                    # A2 for B2
    assert language("French", "C2", "L28") == "covered"                    # native above C2
    assert language("German", "", "L30") == "covered"                      # no level asked: the model's verdict
    [result] = judge([req("German", category="language").model_copy(update={"level": "notions"})],
                     {"r1": answer("missing", ["L30"])})
    assert result.verdict == "covered"                                     # the code reads the level, not the model


def test_weak_or_old_levels_cap_a_must_requirement_at_partial():
    results = judge([req("Java"), req("Java", kind="nice"), req("Azure"), req("Active Directory")], {
        "r1": answer("covered", ["L25"]), "r2": answer("covered", ["L25"]), "r3": answer("covered", ["L24"]),
        "r4": answer("covered", ["L15"])})
    assert [m.verdict for m in results] == ["partial", "covered", "partial", "partial"]
    assert results[0].notes == ["level [Cours] (ancien): covered -> partial"]


def test_the_strongest_accepted_line_gives_the_level():
    [result] = judge([req("Python")], {"r1": answer("covered", ["L25", "L19", "L13"])})
    assert result.level.level == "Pro" and result.line.id == "L25"


def test_a_requirement_with_options_is_covered_when_one_option_is():
    requirement = req("SIEM", category="tool", options=["QRadar", "Splunk", "Sentinel"])
    assert compare.answer_ids([req("Python"), requirement]) == [["r1"], ["r2_o1", "r2_o2", "r2_o3"]]
    [result] = judge([requirement], {"r1_o1": answer("missing"), "r1_o2": answer("covered", ["L11"]),
                                     "r1_o3": answer("unknown")})
    assert (result.verdict, result.option, result.level.level) == ("covered", "Splunk", "Pro")


def test_min_years_above_the_total_experience_caps_at_partial():
    results = judge([req("SOC experience", category="experience", min_years=3),
                     req("SOC experience", category="experience", min_years=1)],
                    {"r1": answer("covered", ["L10"]), "r2": answer("covered", ["L10"])})
    assert [m.verdict for m in results] == ["partial", "covered"]
    assert results[0].notes == ["total experience 2 years < 3: covered -> partial"]


def test_an_answer_outside_the_schema_is_unknown():
    [result] = judge([req("Python")], {"r1": {"verdict": "yes"}})
    assert result.verdict == "unknown"
    [result] = judge([req("Python")], {})
    assert result.verdict == "unknown"


def test_the_schema_has_one_required_field_per_requirement_or_option():
    schema = compare.schema_for([req("Python"), req("Cloud", options=["AWS", "Azure"])]).model_json_schema()
    assert schema["required"] == ["r1", "r2_o1", "r2_o2"]


def test_the_profile_is_sent_numbered():
    prompt = compare.user_prompt([req("Python")], PROFILE)
    assert "L13 [2. Expérience professionnelle] - Scripts d'automatisation en Python [Pro]" in prompt


# ---------- score ----------

def test_match_score_weights_and_values():
    requirements = [req("Python"), req("Go"), req("Terraform", kind="nice"), req("Team player", category="soft_skill"),
                    req("Rust")]
    results = judge(requirements, {"r1": answer("covered", ["L13"]), "r2": answer("partial", ["L25"]),
                                   "r3": answer("missing"), "r4": answer("unknown"), "r5": answer("missing")})
    # must 2 x (1 + 0.5 + 0), nice 1 x 0, soft skill 0.25 x 0.25: 3.0625 / 7.25
    assert compare.score(requirements, results, PROFILE).percent == round(100 * 3.0625 / 7.25, 1)
    assert compare.score([], [], PROFILE).percent == 0


def test_blocking_gaps():
    german = req("German", category="language").model_copy(update={"level": "B2"})
    requirements = [german, req("German", kind="nice", category="language"),
                    req("SOC", category="experience", min_years=5), req("SOC", category="experience", min_years=3)]
    results = judge(requirements, {"r1": answer("covered", ["L30"]), "r2": answer("missing"),
                                   "r3": answer("covered", ["L10"]), "r4": answer("covered", ["L10"])})
    assert compare.score(requirements, results, PROFILE).blocking == [
        "German B2: missing", "SOC: 5 years asked, 2 in the profile"]       # 3 years: within the margin


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
        return json.dumps({i: self.verdicts.get(i, answer("covered", ["L13"])) for i in ids}), "ollama:fake"


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
                yield AIMessageChunk(content=json.dumps({i: answer("covered", ["L13"]) for i in ids}),
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
    out = capsys.readouterr().out
    assert "match 100% | step 1 score 90" in out and "must: 1 covered, 0 partial, 0 missing, 0 unknown" in out
    assert "strengths: Python" in out and "L13" not in out                  # the detail only with --details
    match_offers.main(["--top", "1", "--details"])
    assert "L13 - Scripts d'automatisation en Python [Pro]" in capsys.readouterr().out
    assert len(clients.cloud_prompts) == 1 and len(clients.local_prompts) == 2
    assert store.scores() == {("Bank", "a"): (100.0, [])}
    stored_answers = json.dumps(store.stored("Bank", "a")["answers"], ensure_ascii=False)
    profile_lines = [line.strip() for line in PROFILE.splitlines() if len(line.strip()) > 12]
    for prompt in clients.cloud_prompts:
        assert not any(line in prompt for line in profile_lines)
        assert "Python [Pro]" not in prompt and stored_answers not in prompt and "L13" not in prompt
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
        imports = _imports(path)
        if relative == "scripts/match_offers.py":
            continue
        if relative == "scripts/show_offers.py":             # the match percent only, for --by-match
            imports -= {"job_watch.matching.store", "job_watch.matching.store.scores"}
        assert not any(i.startswith(("job_watch.matching.store", "job_watch.matching.compare",
                                     "job_watch.matching.profile")) for i in imports), relative


def test_the_modules_that_read_personal_data_have_no_cloud_access():
    cloud = {"job_watch.llm.structured_llm", "job_watch.llm.tool_llm", "job_watch.llm.call_with_retry",
             "job_watch.llm._client", "job_watch.llm.llm_chain"}
    for name in ("compare", "store", "profile"):
        imports = _imports(ROOT / "job_watch" / "matching" / f"{name}.py")
        assert not imports & cloud, name

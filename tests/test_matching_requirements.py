"""Matching brick 1: requirements of an offer, checked in code; the local-only guard (no LLM)."""
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from job_watch import config, llm
from job_watch.matching import requirements as req
from job_watch.matching.profile import read_profile
from job_watch.offers.ask_criteria import OfferInput

AD = ("About us: a great bank with free coffee. Your profile: 3 years of experience in a SOC. "
      "Strong Python skills. Experience with a SIEM. German is a plus.")
OFFER = OfferInput(company="Bank", title="SOC Analyst", location="Geneva", ad=AD)


def item(quote, label, kind="must", category="skill"):
    return {"quote": quote, "kind": kind, "category": category, "label": label}


def fake_models(monkeypatch, structured_reply, draft="must ; skill ; Python ; \"Strong Python skills\""):
    seen = {}
    def structured(schema, think):
        def answer(messages):
            seen["format"] = messages
            return structured_reply
        assert think is False
        return RunnableLambda(answer)
    def text(think):
        def answer(messages):
            seen["draft"] = messages
            return AIMessage(content=draft)
        assert think is True
        return RunnableLambda(answer)
    monkeypatch.setattr(req, "local_structured_llm", structured)
    monkeypatch.setattr(req, "local_text_llm", text)
    return seen


def test_invented_quote_is_dropped_and_good_ones_kept(monkeypatch):
    seen = fake_models(monkeypatch, {"requirements": [
        item("Strong Python skills", "Python"),
        item("3 years of experience in a SOC", "3 years experience", category="experience"),
        item("German is a plus", "German", kind="nice", category="language"),
        item("Kubernetes certification required", "Kubernetes", category="certification")]})
    extraction = req.extract_requirements(OFFER)
    assert [r.label for r in extraction.requirements] == ["Python", "3 years experience", "German"]
    assert extraction.requirements[2].kind == "nice"
    assert [d.reason for d in extraction.dropped] == ["quote not in the offer"]
    assert "Strong Python skills" in seen["format"][1][1]               # the draft reaches the second call
    assert "<draft>" in seen["format"][1][1] and "<offer>" in seen["draft"][1][1]


def test_category_or_kind_outside_the_list_is_refused():
    kept, dropped = req.check_requirements([
        item("Strong Python skills", "Python", category="programming"),
        item("Experience with a SIEM", "SIEM", kind="required", category="tool"),
        item("Experience with a SIEM", "SIEM", category="tool")], AD)
    assert [r.label for r in kept] == ["SIEM"]
    assert [d.reason for d in dropped] == ["invalid category", "invalid kind"]


def test_duplicates_long_labels_and_extra_fields_are_dropped():
    kept, dropped = req.check_requirements([
        item("Strong Python skills", "  Python "), item("Strong Python skills", "python"),
        item("Experience with a SIEM", "x" * 61, category="tool"),
        {**item("Experience with a SIEM", "SIEM", category="tool"), "score": 5}], AD)
    assert [r.label for r in kept] == ["Python"]
    assert [d.reason for d in dropped] == ["duplicate", "label empty or too long", "invalid score"]


def test_without_reasoning_one_structured_call(monkeypatch):
    monkeypatch.setattr(config, "MATCH_THINK", False)
    seen = fake_models(monkeypatch, {"requirements": [item("Strong Python skills", "Python")]})
    assert [r.label for r in req.extract_requirements(OFFER).requirements] == ["Python"]
    assert "draft" not in seen


def test_every_model_failed_gives_a_failed_extraction(monkeypatch):
    monkeypatch.setattr(req, "call_with_retry", lambda func, *args: None)
    fake_models(monkeypatch, {"requirements": []})
    assert req.extract_requirements(OFFER).failed


@pytest.mark.parametrize("chain", [
    [("ollama", "qwen3:8b", True), ("gemini", "gemini-3.5-flash-lite", True)],
    [("gemini", "gemini-3.5-flash-lite", False), ("ollama", "qwen3:8b", True)],     # even disabled
])
def test_a_cloud_model_in_the_match_chain_stops_the_program(monkeypatch, tmp_path, chain):
    monkeypatch.setattr(config, "MATCH_CHAIN", chain)
    profile = tmp_path / "profile.md"
    profile.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(config, "PROFILE_PATH", profile)
    with pytest.raises(SystemExit, match="gemini:gemini-3.5-flash-lite"):
        read_profile()
    with pytest.raises(SystemExit, match="only hold local models"):
        llm.local_structured_llm(req.Requirements, think=False)
    with pytest.raises(SystemExit):
        llm.local_text_llm(think=True)


def test_local_chain_reads_the_profile_and_builds_local_clients_only(monkeypatch):
    monkeypatch.setattr(config, "MATCH_CHAIN", [("ollama", "qwen3:8b", True), ("ollama", "other", False)])
    monkeypatch.setattr(config, "PROFILE_PATH", config.BASE_DIR / "tests" / "fixtures" / "profile_example.md")
    assert "## 6. Langues" in read_profile()
    built = []
    monkeypatch.setattr(llm, "_client", lambda p, m, think=None: built.append((p, m, think)) or RunnableLambda(str))
    llm.local_text_llm(think=True)
    assert built == [("ollama", "qwen3:8b", True)]

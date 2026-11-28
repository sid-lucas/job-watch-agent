"""Matching brick 1: requirements of an offer (MODEL_CHAIN, local fallback), checked in code and
stored; local calls with a deadline and a token limit; the local-only guard (no LLM: fake models
and a fake clock)."""
import json

import pytest
from langchain_core.messages import AIMessageChunk

from job_watch import config, llm
from job_watch.matching import requirements as req
from job_watch.matching.profile import read_profile
from job_watch.offers.ask_criteria import OfferInput
from job_watch.offers.criteria import quote_in

AD = ("About us: a great bank with free coffee. Your profile: 3 years of experience in a SOC. "
      "Strong Python skills. Experience with a SIEM. German is a plus. "
      "Familiarity with generative AI, AI agents and the tools that build them.")
OFFER = OfferInput(company="Bank", title="SOC Analyst", location="Geneva", ad=AD)


def item(quote, label, kind="must", category="skill", options=(), min_years=None, level=""):
    return {"quote": quote, "kind": kind, "category": category, "label": label, "options": list(options),
            "min_years": min_years, "level": level}


LOCAL_ONLY = [("ollama", "qwen3:8b")]


def fake_calls(monkeypatch, items, draft="must ; skill ; Python ; \"Strong Python skills\"", fail=None):
    """Only the local model in MODEL_CHAIN; req.local_call replaced: the draft, then the JSON list.
    fail: {call number: reason} of failed calls."""
    monkeypatch.setattr(req, "llm_chain", lambda chain=None: LOCAL_ONLY)
    seen = []
    def local_call(messages, max_tokens, timeout, think=False, schema=None, chain=None):
        seen.append({"messages": messages, "think": think, "schema": schema, "max_tokens": max_tokens,
                     "chain": chain})
        if fail and len(seen) in fail:
            raise llm.LocalCallFailed(fail[len(seen)])
        return (json.dumps({"requirements": items}) if schema else draft), "ollama:fake"
    monkeypatch.setattr(req, "local_call", local_call)
    return seen


def fake_cloud(monkeypatch, reply):
    """A cloud model first in MODEL_CHAIN, answering `reply` (None: every cloud model failed)."""
    monkeypatch.setattr(req, "llm_chain", lambda chain=None: [("gemini", "g"), *LOCAL_ONLY])
    monkeypatch.setattr(req, "only_local_left", lambda chain=None: False)
    seen = []
    class Chain:
        def invoke(self, messages):
            seen.append(messages)
            return reply
    def structured(schema, models, timeout=None):
        seen.append(models)
        seen.append(timeout)
        return Chain()
    monkeypatch.setattr(req, "structured_llm", structured)
    monkeypatch.setattr(req, "call_with_retry", lambda func, *args: func(*args))
    return seen


def test_public_ad_goes_to_the_cloud_models_in_one_structured_call(monkeypatch):
    seen = fake_cloud(monkeypatch, req.Requirements(requirements=[
        req.Requirement(**item("Strong Python skills", "Python"))]))
    local = fake_calls(monkeypatch, [])
    monkeypatch.setattr(req, "llm_chain", lambda chain=None: [("gemini", "g"), *LOCAL_ONLY])
    extraction = req.extract_requirements(OFFER)
    assert [r.label for r in extraction.requirements] == ["Python"] and extraction.raw[0]["label"] == "Python"
    assert seen[0] == (("gemini", "g"),) and local == []                 # cloud models only, no local call
    assert seen[1] == config.REQUIREMENTS_TIMEOUT


def test_every_cloud_model_failed_falls_back_to_the_local_model(monkeypatch):
    fake_cloud(monkeypatch, None)
    local = fake_calls(monkeypatch, [item("Strong Python skills", "Python")])
    monkeypatch.setattr(req, "llm_chain", lambda chain=None: [("gemini", "g"), *LOCAL_ONLY])
    assert [r.label for r in req.extract_requirements(OFFER).requirements] == ["Python"]
    assert len(local) == 2 and local[0]["chain"] == [("ollama", "qwen3:8b", True)]


def test_the_requirements_use_their_own_chain_most_capable_models_first():
    assert config.REQUIREMENTS_CHAIN[0][1] == "gemini-3.8-flash"
    assert config.REQUIREMENTS_CHAIN[-1][0] in config.LOCAL_PROVIDERS


def test_a_label_too_long_is_cut_and_an_empty_one_comes_from_the_quote():
    long = "Familiarity with generative AI, AI agents and the tools that build them, in a bank"
    kept, dropped, notes = req.check_requirements([
        item("Familiarity with generative AI, AI agents and the tools that build them", long),
        item("Experience with a SIEM", "  ", category="tool")], AD)
    assert dropped == []
    assert kept[0].label == "Familiarity with generative AI, AI agents and the tools…"
    assert len(kept[0].label) <= req.MAX_LABEL_CHARS
    assert kept[1].label == "Experience with a SIEM"


def test_alternatives_years_and_levels_are_checked_and_corrected():
    ad = ("3-5 years of experience with Python or Go. Bachelor in computer science or equivalent. "
          "Fluent English (C1). At least two years in a SOC. Strong Python skills.")
    kept, dropped, notes = req.check_requirements([
        item("3-5 years of experience with Python or Go", "3 years experience", category="experience",
             options=["Python", " Go ", "python"], min_years=3),
        item("Bachelor in computer science or equivalent", "Bachelor", category="education",
             options=["computer science"]),                                  # one option: no choice
        item("Fluent English (C1)", "English", category="language", level=" C1 "),
        item("At least two years in a SOC", "2 years in a SOC", category="experience", min_years=2),
        item("Strong Python skills", "Python", min_years=5, level="expert")], ad)
    assert dropped == []
    assert [(r.options, r.min_years, r.level) for r in kept] == [
        (["Python", "Go"], 3, ""), ([], None, ""), ([], None, "C1"), ([], 2, ""), ([], None, "")]
    assert notes == ["Python: min_years 5 not stated in the quote, removed"]     # an invented number


def test_soft_skills_are_a_category_of_their_own():
    kept, _, _ = req.check_requirements([item("Strong Python skills", "Team player", category="soft_skill")], AD)
    assert kept[0].category == "soft_skill"


def test_category_or_kind_outside_the_list_is_refused():
    kept, dropped, notes = req.check_requirements([
        item("Strong Python skills", "Python", category="programming"),
        item("Experience with a SIEM", "SIEM", kind="required", category="tool"),
        item("Experience with a SIEM", "SIEM", category="tool")], AD)
    assert [r.label for r in kept] == ["SIEM"]
    assert [d.reason for d in dropped] == ["invalid category", "invalid kind"]


def test_duplicates_and_extra_fields_are_dropped():
    kept, dropped, notes = req.check_requirements([
        item("Strong Python skills", "  Python "), item("Strong Python skills", "python"),
        {**item("Experience with a SIEM", "SIEM", category="tool"), "score": 5}], AD)
    assert [r.label for r in kept] == ["Python"]
    assert [d.reason for d in dropped] == ["duplicate", "invalid score"]


def test_local_without_reasoning_one_structured_call(monkeypatch):
    monkeypatch.setattr(config, "MATCH_THINK", False)
    seen = fake_calls(monkeypatch, [item("Strong Python skills", "Python")])
    assert [r.label for r in req.extract_requirements(OFFER).requirements] == ["Python"]
    assert [c["schema"] for c in seen] == [req.Requirements]


def test_a_timeout_fails_the_offer(monkeypatch):
    seen = fake_calls(monkeypatch, [], fail={1: "timeout"})
    lines = []
    extraction = req.extract_requirements(OFFER, log=lines.append)
    assert extraction.failure == "timeout" and extraction.requirements == []
    assert len(seen) == 1 and lines[-1].startswith("local call 1/2 (draft, reasoning) failed (timeout) after ")


def test_reasoning_too_long_is_replaced_by_one_call_without_reasoning(monkeypatch):
    seen = fake_calls(monkeypatch, [item("Strong Python skills", "Python")], fail={1: "too long"})
    lines = []
    extraction = req.extract_requirements(OFFER, log=lines.append)
    assert [r.label for r in extraction.requirements] == ["Python"]
    assert [(c["think"], c["schema"]) for c in seen] == [(True, None), (False, req.Requirements)]
    assert "<draft>" not in seen[1]["messages"][1][1]
    assert "reasoning too long: one call without reasoning instead" in lines


def test_a_list_too_long_after_the_reasoning_fails(monkeypatch):
    fake_calls(monkeypatch, [], fail={2: "too long"})
    assert req.extract_requirements(OFFER).failure == "too long"


def test_requirements_are_stored_and_never_extracted_twice(monkeypatch, tmp_path):
    from job_watch.offers import storage
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "offers.db")
    storage.save_offers([{"company": "Bank", "key": "a", "link": "", "title": "SOC Analyst", "location": "Geneva",
                          "description": AD, "source": "career_site", "score": 30, "status": "new", "reasons": []}])
    seen = fake_calls(monkeypatch, [item("Strong Python skills", "Python"), item("invented words", "X")])
    first = req.requirements_of(storage.offer_by_id(1))
    assert not first.reused and len(seen) == 2
    stored = storage.offer_by_id(1)
    assert stored["ad_requirements_model"] == "ollama:fake" and stored["ad_requirements_prompt"] == req.PROMPT_ID
    assert len(stored["ad_requirements"]) == 2                              # raw items, checked again when read
    again = req.requirements_of(stored)
    assert again.reused and len(seen) == 2 and [r.label for r in again.requirements] == ["Python"]
    assert [d.reason for d in again.dropped] == ["quote not in the offer"]
    req.requirements_of(stored, refresh=True)
    assert len(seen) == 4
    storage.save_requirements("Bank", "a", [], "m", "other instructions")
    assert not req.requirements_of(storage.offer_by_id(1)).reused       # other fingerprint: extracted again


def test_a_failed_extraction_is_not_stored(monkeypatch, tmp_path):
    from job_watch.offers import storage
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "offers.db")
    storage.save_offers([{"company": "Bank", "key": "a", "link": "", "title": "T", "description": AD,
                          "source": "career_site", "score": 30, "status": "new", "reasons": []}])
    fake_calls(monkeypatch, [], fail={1: "timeout"})
    assert req.requirements_of(storage.offer_by_id(1)).failure == "timeout"
    assert storage.offer_by_id(1)["ad_requirements"] is None


def test_markdown_and_typographic_marks_do_not_drop_a_quote():
    ad = "Expérience avec LangChain et/ou **pydantic-ai** (agents, chains, tools, memory, RAG)."
    quote = "Expérience avec LangChain et/ou pydantic-ai (agents, chains, tools, memory, RAG)."
    kept, dropped, notes = req.check_requirements([item(quote, "LangChain or pydantic-ai", category="tool")], ad)
    assert dropped == [] and len(kept) == 1
    assert quote_in("l’expérience « en équipe »", "Nous valorisons l'expérience \"en   équipe\".")
    assert quote_in("**pydantic-ai**", "Expérience avec pydantic-ai")
    assert not quote_in("Expérience avec LangChain ou pydantic-ai", ad)        # still word for word


def test_an_answer_that_is_not_a_list_fails_the_offer(monkeypatch):
    fake_calls(monkeypatch, [])
    monkeypatch.setattr(req, "_raw_items", lambda reply: None)
    assert req.extract_requirements(OFFER).failure == "invalid answer"


# ---------- llm.local_call: deadline and token limit ----------

class FakeStream:
    """A local model answering piece by piece; each piece takes `step` seconds of the fake clock."""

    def __init__(self, clock, pieces, step, done_reason="stop"):
        self.clock, self.pieces, self.step, self.done_reason = clock, pieces, step, done_reason
        self.closed, self.built = False, []

    def client(self, provider, model, think=None, max_tokens=None):
        self.built.append((provider, model, think, max_tokens))
        return self

    def stream(self, messages, **options):
        self.options = options
        try:
            for i, piece in enumerate(self.pieces):
                self.clock[0] += self.step
                last = i == len(self.pieces) - 1
                yield AIMessageChunk(content=piece, response_metadata={"done_reason": self.done_reason} if last else {})
        finally:
            self.closed = True


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(llm, "_monotonic", lambda: now[0])
    monkeypatch.setattr(config, "MATCH_CHAIN", [("ollama", "qwen3:8b", True)])
    return now


def test_local_call_returns_the_text_and_the_model(monkeypatch, clock):
    fake = FakeStream(clock, ['{"requirements"', ': []}'], step=10)
    monkeypatch.setattr(llm, "_client", fake.client)
    assert llm.local_call([("user", "x")], max_tokens=100, timeout=60, schema=req.Requirements) == \
        ('{"requirements": []}', "ollama:qwen3:8b")
    assert fake.built == [("ollama", "qwen3:8b", False, 100)]
    assert fake.options["format"]["title"] == "Requirements" and fake.closed


def test_a_model_that_keeps_reasoning_is_stopped_at_the_deadline(monkeypatch, clock):
    fake = FakeStream(clock, [""] * 1000, step=1)       # reasoning pieces: no content, never done
    monkeypatch.setattr(llm, "_client", fake.client)
    with pytest.raises(llm.LocalCallFailed, match="timeout"):
        llm.local_call([("user", "x")], max_tokens=100, timeout=180, think=True)
    assert fake.closed and 180 <= clock[0] <= 182               # the stream is closed, not read to the end


def test_an_answer_cut_by_the_token_limit_fails(monkeypatch, clock):
    fake = FakeStream(clock, ["must ; skill"], step=1, done_reason="length")
    monkeypatch.setattr(llm, "_client", fake.client)
    with pytest.raises(llm.LocalCallFailed, match="too long"):
        llm.local_call([("user", "x")], max_tokens=10, timeout=60)


# ---------- local-only guard ----------

@pytest.mark.parametrize("chain", [
    [("ollama", "qwen3:8b", True), ("gemini", "gemini-3.5-flash-lite", True)],
    [("gemini", "gemini-3.5-flash-lite", False), ("ollama", "qwen3:8b", True)],     # even disabled
])
def test_a_cloud_model_in_the_match_chain_stops_the_program(monkeypatch, tmp_path, chain):
    monkeypatch.setattr(config, "MATCH_CHAIN", chain)
    profile = tmp_path / "profile.md"
    profile.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(config, "PROFILE_PATH", profile)
    built = []
    monkeypatch.setattr(llm, "_client", lambda *args, **kwargs: built.append(args))
    with pytest.raises(SystemExit, match="gemini:gemini-3.5-flash-lite"):
        read_profile()
    with pytest.raises(SystemExit, match="only hold local models"):
        llm.local_call([("user", "x")], max_tokens=10, timeout=60)
    assert built == []                                          # no client built, not even the local one


def test_local_chain_reads_the_profile(monkeypatch):
    monkeypatch.setattr(config, "MATCH_CHAIN", [("ollama", "qwen3:8b", True), ("ollama", "other", False)])
    monkeypatch.setattr(config, "PROFILE_PATH", config.BASE_DIR / "tests" / "fixtures" / "profile_example.md")
    assert "## 6. Langues" in read_profile()
    assert llm.local_models(config.MATCH_CHAIN) == (("ollama", "qwen3:8b"),)

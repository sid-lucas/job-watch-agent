"""Matching brick 1: requirements of an offer, checked in code; local calls with a deadline and a
token limit; the local-only guard (no LLM: fake models and a fake clock)."""
import json

import pytest
from langchain_core.messages import AIMessageChunk

from job_watch import config, llm
from job_watch.matching import requirements as req
from job_watch.matching.profile import read_profile
from job_watch.offers.ask_criteria import OfferInput

AD = ("About us: a great bank with free coffee. Your profile: 3 years of experience in a SOC. "
      "Strong Python skills. Experience with a SIEM. German is a plus. "
      "Familiarity with generative AI, AI agents and the tools that build them.")
OFFER = OfferInput(company="Bank", title="SOC Analyst", location="Geneva", ad=AD)


def item(quote, label, kind="must", category="skill"):
    return {"quote": quote, "kind": kind, "category": category, "label": label}


def fake_calls(monkeypatch, items, draft="must ; skill ; Python ; \"Strong Python skills\"", fail=None):
    """req.local_call replaced: call 1 gives the draft, call 2 the JSON list; fail: reason of a failure."""
    seen = []
    def local_call(messages, max_tokens, timeout, think=False, schema=None):
        seen.append({"messages": messages, "think": think, "schema": schema, "max_tokens": max_tokens})
        if fail:
            raise llm.LocalCallFailed(fail)
        return (json.dumps({"requirements": items}) if schema else draft), "ollama:fake"
    monkeypatch.setattr(req, "local_call", local_call)
    return seen


def test_invented_quote_is_dropped_and_good_ones_kept(monkeypatch):
    seen = fake_calls(monkeypatch, [
        item("Strong Python skills", "Python"),
        item("3 years of experience in a SOC", "3 years experience", category="experience"),
        item("German is a plus", "German", kind="nice", category="language"),
        item("Kubernetes certification required", "Kubernetes", category="certification")])
    lines = []
    extraction = req.extract_requirements(OFFER, log=lines.append)
    assert [r.label for r in extraction.requirements] == ["Python", "3 years experience", "German"]
    assert extraction.requirements[2].kind == "nice" and extraction.model == "ollama:fake"
    assert [d.reason for d in extraction.dropped] == ["quote not in the offer"]
    assert [(c["think"], c["schema"]) for c in seen] == [(True, None), (False, req.Requirements)]
    assert [c["max_tokens"] for c in seen] == [config.MATCH_DRAFT_MAX_TOKENS, config.MATCH_FORMAT_MAX_TOKENS]
    assert "Strong Python skills" in seen[1]["messages"][1][1] and "<draft>" in seen[1]["messages"][1][1]
    assert [line[:8] for line in lines] == ["call 1/2"] * 2 + ["call 2/2"] * 2
    assert lines[0] == "call 1/2 (draft, reasoning) started" and lines[3].startswith("call 2/2 done in ")


def test_a_label_too_long_is_cut_and_an_empty_one_comes_from_the_quote():
    long = "Familiarity with generative AI, AI agents and the tools that build them, in a bank"
    kept, dropped = req.check_requirements([
        item("Familiarity with generative AI, AI agents and the tools that build them", long),
        item("Experience with a SIEM", "  ", category="tool")], AD)
    assert dropped == []
    assert kept[0].label == "Familiarity with generative AI, AI agents and the tools…"
    assert len(kept[0].label) <= req.MAX_LABEL_CHARS
    assert kept[1].label == "Experience with a SIEM"


def test_category_or_kind_outside_the_list_is_refused():
    kept, dropped = req.check_requirements([
        item("Strong Python skills", "Python", category="programming"),
        item("Experience with a SIEM", "SIEM", kind="required", category="tool"),
        item("Experience with a SIEM", "SIEM", category="tool")], AD)
    assert [r.label for r in kept] == ["SIEM"]
    assert [d.reason for d in dropped] == ["invalid category", "invalid kind"]


def test_duplicates_and_extra_fields_are_dropped():
    kept, dropped = req.check_requirements([
        item("Strong Python skills", "  Python "), item("Strong Python skills", "python"),
        {**item("Experience with a SIEM", "SIEM", category="tool"), "score": 5}], AD)
    assert [r.label for r in kept] == ["Python"]
    assert [d.reason for d in dropped] == ["duplicate", "invalid score"]


def test_without_reasoning_one_structured_call(monkeypatch):
    monkeypatch.setattr(config, "MATCH_THINK", False)
    seen = fake_calls(monkeypatch, [item("Strong Python skills", "Python")])
    assert [r.label for r in req.extract_requirements(OFFER).requirements] == ["Python"]
    assert [c["schema"] for c in seen] == [req.Requirements]


@pytest.mark.parametrize("reason", ["timeout", "too long"])
def test_a_failed_call_fails_the_offer_with_its_reason(monkeypatch, reason):
    seen = fake_calls(monkeypatch, [], fail=reason)
    lines = []
    extraction = req.extract_requirements(OFFER, log=lines.append)
    assert extraction.failure == reason and extraction.requirements == []
    assert len(seen) == 1 and lines[-1].startswith(f"call 1/2 failed ({reason}) after ")


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

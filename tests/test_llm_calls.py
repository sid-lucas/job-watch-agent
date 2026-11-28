"""Calls counted per model of the chain, with fake chat models (no network)."""
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from job_watch import llm


def test_calls_are_counted_per_model_through_fallbacks():
    failing = FakeListChatModel(responses=[], callbacks=[llm._CallCounter("fake:cloud")])
    local = FakeListChatModel(responses=["a", "b"], callbacks=[llm._CallCounter("fake:local")])
    chain = failing.with_fallbacks([local])
    before = llm.model_calls()
    chain.invoke("x")
    chain.invoke("y")
    assert llm.calls_since(before) == {"fake:cloud failed": 2, "fake:local": 2}
    assert llm.calls_since(llm.model_calls()) == {}


# ---------- rate limits and quotas ----------

import httpx
from google.genai.errors import ClientError
from langchain_google_genai.chat_models import GoogleRateLimitError
from langchain_mistralai.chat_models import MistralAIAuthenticationError, MistralAIRateLimitError


def google_429(quota_id: str, retry_delay: str | None = "41s"):
    """A Gemini 429 as langchain_google_genai raises it: the google-genai ClientError as cause."""
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaMetric": "generate_content_free_tier_requests", "quotaId": quota_id}]}]
    if retry_delay:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay})
    cause = ClientError(429, {"error": {"code": 429, "message": "You exceeded your current quota.",
                                        "status": "RESOURCE_EXHAUSTED", "details": details}})
    error = GoogleRateLimitError(f"Error calling model 'gemini-x' (RESOURCE_EXHAUSTED): {cause}")
    error.__cause__ = cause
    return error


def mistral_error(error_type, status: int, body: str, headers: dict | None = None):
    request = httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions")
    response = httpx.Response(status, headers=headers or {}, text=body, request=request)
    return error_type(f"Error response {status} while fetching {request.url}: {body}", request=request,
                      response=response)


@pytest.mark.parametrize("error, expected", [
    (google_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"), ("per_minute", 41.0)),
    (google_429("GenerateContentInputTokensPerModelPerMinute-FreeTier", None), ("per_minute", None)),
    (google_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier"), ("daily", None)),
    (RuntimeError("429 RESOURCE_EXHAUSTED. {'error': {'details': [{'quotaId': 'GenerateRequestsPerDayPerProject'}]}}"),
     ("daily", None)),                                                       # text only, no structure
    (RuntimeError("429 RESOURCE_EXHAUSTED. {'quotaId': 'SomethingPerMinute', 'retryDelay': '7s'}"), ("per_minute", 7.0)),
    (mistral_error(MistralAIRateLimitError, 429, '{"message":"Requests rate limit exceeded"}', {"retry-after": "2"}),
     ("per_minute", 2.0)),
    (mistral_error(MistralAIRateLimitError, 429, '{"message":"Too many requests"}'), ("unknown_quota", None)),
    (mistral_error(MistralAIAuthenticationError, 401, '{"message":"Unauthorized"}'), ("auth", None)),
    (mistral_error(httpx.HTTPStatusError, 402, '{"message":"Payment Required"}'), ("auth", None)),  # no free tier
    (RuntimeError("Error response 402 while fetching https://api.example/v1/chat"), ("auth", None)),
    (TimeoutError("read timed out"), ("other", None)),
])
def test_classify_failure(error, expected):
    assert llm.classify_failure(error) == expected


class Failing(FakeListChatModel):
    """Raises the next error of the list, then answers like FakeListChatModel."""
    errors: list = []

    def _call(self, *args, **kwargs):
        if self.errors:
            raise self.errors.pop(0)
        return super()._call(*args, **kwargs)


@pytest.fixture
def policy(monkeypatch):
    waits = []
    monkeypatch.setattr(llm, "_unavailable", {})
    monkeypatch.setattr(llm, "_overloaded", llm.Counter())
    monkeypatch.setattr(llm, "_sleep", waits.append)
    return waits


def chain_of(cloud_errors, name="fake:cloud"):
    cloud = Failing(responses=["cloud"] * 5, errors=list(cloud_errors), callbacks=[llm._CallCounter(name)])
    local = FakeListChatModel(responses=["local"] * 5, callbacks=[llm._CallCounter(f"{name}-local")])
    return llm._chain([(name, cloud), (f"{name}-local", local)])


def test_a_per_minute_limit_waits_then_retries_the_same_model(policy):
    chain = chain_of([google_429("RequestsPerMinute"), google_429("RequestsPerMinute", "3s")], "fake:minute")
    assert chain.invoke("x").content == "cloud"          # still the cloud model, after two waits
    assert policy == [41.0, 3.0]
    assert "fake:minute" not in llm._unavailable


def test_a_per_minute_limit_that_lasts_goes_to_the_next_model_for_this_call_only(policy):
    chain = chain_of([google_429("RequestsPerMinute", "1s")] * 3, "fake:busy")
    assert chain.invoke("x").content == "local"          # 2 retries spent
    assert chain.invoke("y").content == "cloud"          # not skipped for the run
    assert policy == [1.0, 1.0]


def test_a_long_retry_delay_is_not_waited_for(policy):
    chain = chain_of([google_429("RequestsPerMinute", "300s")], "fake:long")
    assert chain.invoke("x").content == "local" and policy == []
    assert chain.invoke("y").content == "cloud"


def test_a_daily_quota_skips_the_model_for_the_run(policy):
    chain = chain_of([google_429("RequestsPerDay")], "fake:daily")
    before = llm.model_calls()
    assert [chain.invoke(v).content for v in "xyz"] == ["local", "local", "local"]
    assert policy == [] and llm._unavailable["fake:daily"] == "daily"
    assert llm.calls_since(before) == {"fake:daily failed": 1, "fake:daily skipped": 2, "fake:daily-local": 3}


def test_an_unreadable_429_is_retried_once_then_skipped(policy):
    unreadable = mistral_error(MistralAIRateLimitError, 429, '{"message":"Too many requests"}')
    chain = chain_of([unreadable, unreadable], "fake:unknown")
    assert chain.invoke("x").content == "local"
    assert policy == [llm.RATE_LIMIT_DEFAULT_WAIT] and llm._unavailable["fake:unknown"] == "unknown_quota"


def test_a_refused_key_skips_the_model_without_waiting(policy):
    chain = chain_of([mistral_error(MistralAIAuthenticationError, 401, "Unauthorized")], "fake:auth")
    assert chain.invoke("x").content == "local" and chain.invoke("y").content == "local"
    assert policy == [] and llm._unavailable["fake:auth"] == "auth"


def test_other_errors_do_not_skip_the_model(policy):
    chain = chain_of([TimeoutError("read timed out")] * 2, "fake:slow")
    assert chain.invoke("x").content == "local" and chain.invoke("y").content == "local"
    assert chain.invoke("z").content == "cloud" and policy == []


@pytest.mark.allow_llm_client
def test_mistral_is_left_out_without_its_key(monkeypatch):
    monkeypatch.setattr(llm.config, "MODEL_CHAIN", [("gemini", "g", True), ("mistral", "mistral-small-latest", True),
                                                    ("ollama", "q", True)])
    monkeypatch.delenv("LLM_ONLY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    assert [p for p, _ in llm.llm_chain()] == ["gemini", "ollama"]
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key-not-real")
    assert [p for p, _ in llm.llm_chain()] == ["gemini", "mistral", "ollama"]
    client = llm._client("mistral", "mistral-small-latest")          # no network at construction
    assert type(client).__name__ == "ChatMistralAI" and client.model == "mistral-small-latest"


def test_one_chain_in_order_without_disabled_models(monkeypatch):
    monkeypatch.delenv("LLM_ONLY", raising=False)
    monkeypatch.setattr(llm.config, "MODEL_CHAIN", [("gemini", "a", True), ("gemini", "gemma", False),
                                                    ("gemini", "b", True), ("ollama", "q", True)])
    assert llm.llm_chain() == [("gemini", "a"), ("gemini", "b"), ("ollama", "q")]
    monkeypatch.setenv("LLM_ONLY", "ollama")
    assert llm.llm_chain() == [("ollama", "q")]


def test_the_default_chain_holds_no_paid_or_unchecked_model():
    from job_watch import config
    enabled = {f"{p}:{m}" for p, m, on in config.MODEL_CHAIN if on}
    assert "mistral:mistral-small-latest" not in enabled and "gemini:gemma-4-31b-it" not in enabled
    assert not any("2.5" in name for name in enabled)                       # end of life
    assert config.MODEL_CHAIN[-1][0] in config.LOCAL_PROVIDERS               # local model last


def test_only_local_left_once_every_cloud_model_is_skipped(monkeypatch):
    monkeypatch.delenv("LLM_ONLY", raising=False)
    monkeypatch.setattr(llm.config, "MODEL_CHAIN", [("gemini", "a", True), ("gemini", "off", False),
                                                    ("ollama", "q", True)])
    monkeypatch.setattr(llm, "_unavailable", {})
    assert not llm.only_local_left()
    llm._unavailable["gemini:a"] = "daily"
    assert llm.only_local_left()                                           # a disabled model does not count


@pytest.mark.parametrize("error", [RuntimeError("504 DEADLINE_EXCEEDED. Deadline expired"),
                                   RuntimeError("503 UNAVAILABLE. high demand")])
def test_overloaded_errors_are_classified(error):
    assert llm.classify_failure(error) == ("overloaded", None)


def test_a_model_overloaded_twice_is_skipped_for_the_run(policy):
    chain = chain_of([RuntimeError("503 UNAVAILABLE"), RuntimeError("504 DEADLINE_EXCEEDED")], "fake:busy")
    assert chain.invoke("x").content == "local"          # first 503: this call only
    assert "fake:busy" not in llm._unavailable
    assert chain.invoke("y").content == "local"          # second one: skipped for the run
    assert llm._unavailable["fake:busy"] == "overloaded"
    assert chain.invoke("z").content == "local" and policy == []


def test_each_attempt_gets_a_line(policy):
    chain = chain_of([RuntimeError("504 DEADLINE_EXCEEDED")], "gemini:big")
    lines = []
    with llm.attempts_logged(lines.append):
        assert chain.invoke("x").content == "local"
    assert lines[0] == "trying big..."
    assert lines[1].startswith("big failed (504) after ") and lines[1].endswith("s, next model")
    assert lines[2] == "trying big-local..." and lines[3].startswith("big-local done in ")
    chain.invoke("y")                                     # outside the block: no line
    assert len(lines) == 4
    llm._unavailable["gemini:big"] = "overloaded"
    with llm.attempts_logged(lines.append):
        chain.invoke("z")
    assert lines[4] == "big skipped (overloaded for this run)"

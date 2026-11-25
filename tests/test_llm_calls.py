"""Calls counted per model of the chain, with fake chat models (no network)."""
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


def test_a_model_out_of_quota_is_skipped_for_the_rest_of_the_run(monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    monkeypatch.setattr(llm, "_out_of_quota", set())
    tried = []

    class QuotaModel(FakeListChatModel):
        def _call(self, *args, **kwargs):
            tried.append("cloud")
            raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")

    cloud = QuotaModel(responses=[], callbacks=[llm._CallCounter("fake:quota")])
    local = FakeListChatModel(responses=["a", "b", "c"], callbacks=[llm._CallCounter("fake:local2")])
    chain = llm._chain([("fake:quota", cloud), ("fake:local2", local)])
    before = llm.model_calls()
    assert [chain.invoke("x").content for _ in range(3)] == ["a", "b", "c"]
    assert tried == ["cloud"]                       # asked once, then skipped
    assert llm.calls_since(before) == {"fake:local2": 3, "fake:quota failed": 1, "fake:quota skipped": 2}


def test_other_errors_do_not_skip_the_model(monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    monkeypatch.setattr(llm, "_out_of_quota", set())

    class TimeoutModel(FakeListChatModel):
        def _call(self, *args, **kwargs):
            raise TimeoutError("read timed out")

    cloud = TimeoutModel(responses=[], callbacks=[llm._CallCounter("fake:slow")])
    local = FakeListChatModel(responses=["a", "b"], callbacks=[llm._CallCounter("fake:local3")])
    chain = llm._chain([("fake:slow", cloud), ("fake:local3", local)])
    before = llm.model_calls()
    chain.invoke("x")
    chain.invoke("y")
    assert llm.calls_since(before) == {"fake:local3": 2, "fake:slow failed": 2}

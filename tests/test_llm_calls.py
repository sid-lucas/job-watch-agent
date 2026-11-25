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

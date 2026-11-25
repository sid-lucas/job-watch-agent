"""Summaries of old observations in the agent conversation (no LLM, no browser)."""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph.message import add_messages

from job_watch.list_agent.graph import SUMMARY_PREFIX, summarise_old_observations


def observation(n: int, call_id: str) -> ToolMessage:
    return ToolMessage(content=f"<page>full text of page {n}</page>", id=f"obs{n}", tool_call_id=call_id,
                       name="observe", artifact={"title": "Jobs", "new_lines": 20, "elements": 40,
                                                 "current": [str(n)], "names": {8: "Next", 9: "page 3"}})


def conversation() -> list:
    return [
        HumanMessage(content="Read the list.", id="h"),
        AIMessage(content="", id="a1", tool_calls=[{"name": "observe", "args": {}, "id": "c1"}]),
        observation(1, "c1"),
        AIMessage(content="", id="a2", tool_calls=[{"name": "click", "args": {"element_id": 8,
                                                                               "purpose": "pagination"}, "id": "c2"}]),
        ToolMessage(content="Clicked.", id="t2", tool_call_id="c2", name="click"),
        AIMessage(content="", id="a3", tool_calls=[{"name": "observe", "args": {}, "id": "c3"}]),
        observation(2, "c3"),
    ]


def test_only_the_last_observation_stays_in_full():
    summaries = summarise_old_observations(conversation())
    assert [m.id for m in summaries] == ["obs1"]
    assert summaries[0].content == (f"{SUMMARY_PREFIX} page 'Jobs': 20 new lines, 40 elements, current ['1']. "
                                    "Then: click [8] 'Next' (pagination)")
    assert summaries[0].tool_call_id == "c1"           # still paired with its tool call


def test_add_messages_replaces_instead_of_appending():
    messages = conversation()
    merged = add_messages(messages, summarise_old_observations(messages))
    assert len(merged) == len(messages)
    assert merged[2].content.startswith(SUMMARY_PREFIX) and "page 2" in merged[-1].content


def test_summaries_are_made_once():
    merged = add_messages(conversation(), summarise_old_observations(conversation()))
    assert summarise_old_observations(merged) == []

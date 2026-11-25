"""Budgets of the list agent, enforced in code: fake tools and a scripted fake LLM (no browser, no LLM)."""
from itertools import count

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool

from job_watch import config
from job_watch.list_agent import graph
from job_watch.list_agent.state import initial_state
from job_watch.list_agent.tools import back_to_list, click, finish, observe


def fake_tools(never_seen: list[int], click_result: str = "Clicked. Element numbers are now invalid: call observe."):
    """observe returns the next never_seen value (the last one repeats); click always answers click_result."""
    values = iter(never_seen)
    last = {"value": never_seen[-1]}

    def run_observe():
        last["value"] = next(values, last["value"])
        return "<page>...</page>", {"title": "Jobs", "new_lines": 5, "never_seen": last["value"], "elements": 3,
                                    "current": [], "names": {1: "Next"}}

    return [
        StructuredTool.from_function(run_observe, name="observe", description=observe.__doc__, args_schema=observe,
                                     response_format="content_and_artifact"),
        StructuredTool.from_function(lambda element_id, purpose: click_result, name="click",
                                     description=click.__doc__, args_schema=click),
        StructuredTool.from_function(lambda: "Refused", name="back_to_list", description=back_to_list.__doc__,
                                     args_schema=back_to_list),
        StructuredTool.from_function(lambda reason, explanation: f"Finished: {reason}.", name="finish",
                                     description=finish.__doc__, args_schema=finish),
    ]


class ScriptedLLM:
    """Observe first, then alternate click (with the given purpose) and observe, forever."""

    def __init__(self, purpose="pagination"):
        self.calls = 0
        self.purpose = purpose
        self.ids = count(1)

    def invoke(self, messages):
        self.calls += 1
        if self.calls % 2:
            call = {"name": "observe", "args": {}, "id": f"c{next(self.ids)}"}
        else:
            call = {"name": "click", "args": {"element_id": 1, "purpose": self.purpose}, "id": f"c{next(self.ids)}"}
        return AIMessage(content="", tool_calls=[call])


def run(tools, llm, monkeypatch):
    monkeypatch.setattr(graph, "tool_llm", lambda schemas: llm)
    state = initial_state("Example", "https://jobs.example.com")
    state["messages"] = [HumanMessage(content="Company: Example. Read its job list.")]
    return graph.build_graph(tools).invoke(state, {"recursion_limit": 500})


@pytest.fixture(autouse=True)
def limits(monkeypatch):
    monkeypatch.setattr(config, "AGENT_MAX_LLM_CALLS", 50)
    monkeypatch.setattr(config, "AGENT_MAX_CLICKS_WITHOUT_NEW_CONTENT", 3)


def test_clicks_that_bring_nothing_never_seen_stop_the_run(monkeypatch):
    llm = ScriptedLLM()
    final = run(fake_tools([40, 25, 0]), llm, monkeypatch)      # first page, one new page, then pages already seen
    assert final["stop_reason"] == "no_new_content"
    assert final["clicks_without_new_content"] == 3
    # observe(40), click, observe(25): useful; then 3 x (click, observe(0)): 1 + 2 + 6 = 9 calls
    assert llm.calls == 9
    assert final["trail"][-1] == "budget: 3 pagination clicks in a row without new content, stop"


def test_new_content_resets_the_count(monkeypatch):
    llm = ScriptedLLM()
    final = run(fake_tools([40, 0, 0, 12, 0, 0, 0]), llm, monkeypatch)
    assert final["stop_reason"] == "no_new_content"
    # counts after each click: 1, 2, then 0 (the click that brought 12), then 1, 2, 3: 1 + 6 x 2 = 13 calls
    assert llm.calls == 13


def test_the_llm_call_budget_stops_the_run_without_another_call(monkeypatch):
    monkeypatch.setattr(config, "AGENT_MAX_LLM_CALLS", 7)
    llm = ScriptedLLM()
    final = run(fake_tools([40, 10]), llm, monkeypatch)        # always something new: only the LLM budget stops it
    assert final["stop_reason"] == "llm_budget"
    assert llm.calls == 7 and final["llm_calls"] == 7


@pytest.mark.parametrize("purpose, click_result", [
    ("cookie_refusal", "Clicked. Element numbers are now invalid: call observe."),   # not pagination
    ("pagination", "Refused, nothing was clicked: stale_id (id not in the last observation)."),  # nothing clicked
])
def test_only_pagination_clicks_done_are_counted(monkeypatch, purpose, click_result):
    monkeypatch.setattr(config, "AGENT_MAX_LLM_CALLS", 12)
    final = run(fake_tools([40, 0], click_result=click_result), ScriptedLLM(purpose), monkeypatch)
    assert final["stop_reason"] == "llm_budget" and final["clicks_without_new_content"] == 0


def test_finish_still_ends_the_run(monkeypatch):
    class FinishingLLM:
        def invoke(self, messages):
            return AIMessage(content="", tool_calls=[{"name": "finish", "id": "f1", "args": {
                "reason": "no_pagination", "explanation": "One page."}}])

    final = run(fake_tools([40]), FinishingLLM(), monkeypatch)
    assert final["stop_reason"] is None and final["messages"][-1].content == "Finished: no_pagination."


def test_run_list_agent_streams_through_the_budgets_node(monkeypatch):
    """The real run loop (stream, progress lines), with fake tools: a node that changes nothing
    (budgets after observe) streams None, which must not break the loop."""
    from contextlib import nullcontext
    from job_watch.list_agent import run as agent_run
    monkeypatch.setattr(agent_run, "SessionThread", lambda url: nullcontext(type("S", (), {
        "trail": [], "observations": []})()))
    monkeypatch.setattr(agent_run, "make_tools", lambda session: fake_tools([40, 25, 0]))
    llm = ScriptedLLM()                                  # one instance for every turn
    monkeypatch.setattr(graph, "tool_llm", lambda schemas: llm)
    lines = []
    result = agent_run.run_list_agent("https://jobs.example.com", "Example",
                                      on_update=agent_run.progress_printer(lines.append))
    assert result.stop == "no_new_content" and result.llm_calls == 9
    assert lines[-1].startswith("turn 10: stop no_new_content (budget: 3 pagination clicks in a row")

"""Progress lines printed during a run (no LLM, no browser)."""
from langchain_core.messages import AIMessage, ToolMessage

from job_watch.list_agent.run import progress_printer


def test_one_line_per_agent_turn_with_result_model_and_duration():
    lines = []
    on_update = progress_printer(lines.append)
    ask = AIMessage(content="", tool_calls=[{"name": "observe", "args": {}, "id": "1"}],
                    response_metadata={"model_name": "gemini-x"})
    on_update("agent", {"messages": [ask]})
    seen = ToolMessage(content="<page>...</page>", tool_call_id="1", name="observe",
                       artifact={"title": "Jobs", "new_lines": 40, "elements": 120})
    on_update("tools", {"messages": [seen]})
    click = AIMessage(content="", tool_calls=[{"name": "click", "args": {"element_id": 7, "purpose": "pagination"},
                                               "id": "2"}], response_metadata={"model": "qwen3:8b"})
    on_update("agent", {"messages": [click]})
    on_update("tools", {"messages": [ToolMessage(content="Clicked. Element numbers are now invalid.",
                                                 tool_call_id="2", name="click")]})
    on_update("agent", {"messages": [], "stop_reason": "error", "trail": ["llm call 3: every model failed"]})
    assert lines[0].startswith("turn 1: observe() -> 'Jobs', 40 new lines, 120 elements | gemini-x ")
    assert lines[1].startswith("turn 2: click(7, pagination) -> Clicked. Element numbers are now invalid. | qwen3:8b ")
    assert lines[2] == "turn 3: stop error (llm call 3: every model failed)"
    assert len(lines) == 3


def test_offers_rejected_after_the_full_ad_are_listed_by_company(capsys):
    import main
    def offer(key, title, status, full_ad, reasons, source="career_site"):
        return {"company": "Bank", "key": key, "title": title, "status": status, "full_ad": full_ad,
                "reasons": reasons, "source": source}
    result = {"new_offers": [("Bank", k) for k in "abcd"], "offers": [
        offer("a", "Senior Engineer", "rejected", True, ["rejected: senior | 'Senior Engineer'"]),
        offer("b", "Analyst", "new", True, ["SOC (+25): 'SOC'"]),
        offer("c", "Lead", "rejected", False, ["rejected: senior | 'Lead'"]),              # listing only
        offer("d", "Dev", "rejected", False, ["rejected: abroad | 'Paris'"], source="swissdevjobs"),
        offer("e", "Old", "rejected", True, ["rejected: senior | 'Old'"])]}             # not new
    main.show_rejected_after_detail(result)
    assert capsys.readouterr().out == ("\nRejected after the full ad at Bank (1): title | criterion | quote\n"
                                       "  Senior Engineer | senior | 'Senior Engineer'\n")


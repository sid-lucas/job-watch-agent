"""Show how LangGraph merges node updates into the list agent state (no LLM, no browser).

    python -m scripts.try_state
"""
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from job_watch.list_agent.state import ListAgentState, initial_state


def fake_agent(state: ListAgentState) -> dict:
    """Stands in for the LLM node: returns only the fields it changes."""
    n = state["llm_calls"] + 1
    return {
        "messages": [AIMessage(content=f"answer {n}")],    # add_messages: appended
        "llm_calls": n,                                     # no reducer: replaced
        "trail": [f"fake_agent call {n}"],                  # operator.add: appended
    }


def show(title: str, state: dict) -> None:
    print(f"\n--- {title}")
    for key, value in state.items():
        if key == "messages":
            value = [f"{type(m).__name__}(id={m.id[:8] if m.id else None}, {m.content!r})" for m in value]
        print(f"{key:28} {value}")


def main():
    graph = StateGraph(ListAgentState)
    graph.add_node("agent_1", fake_agent)
    graph.add_node("agent_2", fake_agent)
    graph.add_edge(START, "agent_1")
    graph.add_edge("agent_1", "agent_2")
    graph.add_edge("agent_2", END)
    app = graph.compile()

    start = initial_state("Lombard Odier", "https://lombardodier.wd3.myworkdayjobs.com/Lombard_Odier_Careers")
    start["messages"] = [HumanMessage(content="Collect the offers of this list.")]
    show("initial state", start)
    show("after two nodes", app.invoke(start))

    # add_messages alone: same id replaces, new id appends
    old = [HumanMessage(content="first", id="m1")]
    merged = add_messages(old, [HumanMessage(content="first, corrected", id="m1"),
                                HumanMessage(content="second", id="m2")])
    show("add_messages(old, [same id m1, new id m2])", {"messages": merged})


if __name__ == "__main__":
    main()

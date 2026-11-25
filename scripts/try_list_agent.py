"""Run the list agent on one job list and print every node update (navigation only, no extraction),
then a summary: LLM calls and tokens, clicks, refusals, new lines per observation, stop reason.

    python -m scripts.try_list_agent URL [COMPANY]
"""
import sys

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from job_watch.list_agent.graph import build_graph
from job_watch.list_agent.state import initial_state
from job_watch.list_agent.tools import make_tools
from job_watch.web.session import SessionError
from job_watch.web.session_thread import SessionThread

RECURSION_LIMIT = 40    # temporary safety net of LangGraph (node runs), until the budgets piece


def show(node: str, update: dict) -> None:
    for message in update.get("messages", []):
        if message.type == "ai":
            print(f"[{node}] asks: {[(c['name'], c['args']) for c in message.tool_calls] or message.content!r}")
        else:
            content = message.content if len(message.content) < 300 else message.content[:300] + " ..."
            print(f"[{node}] {message.name} -> {content}")
    for line in update.get("trail", []):
        print(f"[{node}] trail: {line}")
    for key in ("llm_calls", "stop_reason"):
        if key in update:
            print(f"[{node}] {key} = {update[key]}")


def summary(session, answers: list, stop: str) -> None:
    trail = session.trail
    clicks = [e.detail for e in trail if e.kind in ("click", "cookie_accepted")]
    refused = [e.detail for e in trail if e.kind == "click_refused"]
    navigation_refused = [e.detail for e in trail if e.kind == "navigation_refused"]
    observes = [e.detail.split(", ")[2] for e in trail if e.kind == "observe"]
    tokens = [a.usage_metadata["input_tokens"] for a in answers if a.usage_metadata]
    print("\n=== summary")
    print(f"stop: {stop}")
    print(f"llm calls: {len(answers)}, input tokens: total {sum(tokens)}, last call {tokens[-1] if tokens else 0}")
    print(f"clicks ({len(clicks)}):")
    for detail in clicks:
        print(f"  {detail[:110]}")
    print(f"clicks refused ({len(refused)}):")
    for detail in refused:
        print(f"  {detail[:110]}")
    print(f"navigations refused ({len(navigation_refused)}):")
    for detail in navigation_refused:
        print(f"  {detail[:110]}")
    print(f"new lines per observation: {observes}")


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    url, company = sys.argv[1], (sys.argv[2] if len(sys.argv) == 3 else "unknown")
    try:
        with SessionThread(url) as session:
            app = build_graph(make_tools(session))
            state = initial_state(company, url)
            state["messages"] = [HumanMessage(content=f"Company: {company}. Read its job list.")]
            answers, stop = [], "no tool call"
            try:
                for chunk in app.stream(state, {"recursion_limit": RECURSION_LIMIT}, stream_mode="updates"):
                    for node, update in chunk.items():
                        print()
                        show(node, update)
                        answers += [m for m in update.get("messages", []) if m.type == "ai"]
                        stop = update.get("stop_reason") or stop
                        stop = next((f"finish: {m.content}" for m in update.get("messages", [])
                                     if m.type == "tool" and m.name == "finish"), stop)
            except GraphRecursionError:
                stop = f"recursion_limit={RECURSION_LIMIT}"
            summary(session, answers, stop)
    except SessionError as error:
        sys.exit(f"session error: {error}")


if __name__ == "__main__":
    main()

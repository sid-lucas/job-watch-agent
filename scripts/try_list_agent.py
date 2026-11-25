"""Run the list agent on one job list and print every node update (navigation only, no extraction).

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


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    url, company = sys.argv[1], (sys.argv[2] if len(sys.argv) == 3 else "unknown")
    try:
        with SessionThread(url) as session:
            app = build_graph(make_tools(session))
            state = initial_state(company, url)
            state["messages"] = [HumanMessage(content=f"Company: {company}. Read its job list.")]
            try:
                for chunk in app.stream(state, {"recursion_limit": RECURSION_LIMIT}, stream_mode="updates"):
                    for node, update in chunk.items():
                        print()
                        show(node, update)
            except GraphRecursionError:
                print(f"\nstopped by recursion_limit={RECURSION_LIMIT}")
            print("\nbrowser trail:")
            for event in session.trail:
                if event.kind != "navigation_allowed":
                    print(f"  {event.seconds:6}s {event.kind:22} {event.detail[:100]}")
    except SessionError as error:
        sys.exit(f"session error: {error}")


if __name__ == "__main__":
    main()

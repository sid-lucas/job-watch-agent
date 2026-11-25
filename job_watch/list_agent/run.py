"""Run the list agent on one job list (navigation only) and collect what the run did.

Shared by scripts/try_list_agent.py (prints every node update) and evals/check_list_navigation.py.
"""
import re
import time

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, ConfigDict

from job_watch.list_agent.graph import build_graph
from job_watch.list_agent.state import initial_state
from job_watch.list_agent.tools import make_tools
from job_watch.web.session import Observation, SessionError, TrailEvent
from job_watch.web.session_thread import SessionThread

RECURSION_LIMIT = 80    # temporary safety net of LangGraph (node runs), until the budgets piece


class AgentRun(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    stop: str                           # finish reason, recursion limit, error...
    explanation: str = ""               # from finish, logged only
    answers: list[AIMessage] = []
    trail: list[TrailEvent] = []        # browser session trail
    observations: list[Observation] = []
    seconds: float = 0

    @property
    def llm_calls(self) -> int:
        return len(self.answers)

    @property
    def input_tokens(self) -> list[int]:
        return [a.usage_metadata["input_tokens"] for a in self.answers if a.usage_metadata]


def pages_reached(trail: list[TrailEvent]) -> int:
    """1 + pagination clicks whose next observation brought new lines, minus clicks undone by back_to_list."""
    pages, pending = 1, False
    for event in trail:
        if event.kind == "click" and " pagination " in event.detail:
            pending = True
        elif event.kind == "observe" and pending:
            found = re.search(r"(\d+) new lines", event.detail)
            pages += 1 if found and int(found.group(1)) > 0 else 0
            pending = False
        elif event.kind == "back_to_list":
            pages -= 1      # the page reached by the click that left the list was not a list page
    return pages


def run_list_agent(url: str, company: str, recursion_limit: int = RECURSION_LIMIT, on_update=None) -> AgentRun:
    """Open the list, run the graph until it stops, return the run. on_update(node, update) is optional."""
    started = time.monotonic()
    answers, stop, explanation = [], "no tool call", ""
    try:
        with SessionThread(url) as session:
            app = build_graph(make_tools(session))
            state = initial_state(company, url)
            state["messages"] = [HumanMessage(content=f"Company: {company}. Read its job list.")]
            try:
                for chunk in app.stream(state, {"recursion_limit": recursion_limit}, stream_mode="updates"):
                    for node, update in chunk.items():
                        if on_update:
                            on_update(node, update)
                        for message in update.get("messages", []):
                            if message.type == "ai":
                                answers.append(message)
                                for call in message.tool_calls:
                                    if call["name"] == "finish":
                                        explanation = call["args"].get("explanation", "")
                            elif message.type == "tool" and message.name == "finish":
                                stop = f"finish: {message.content.removeprefix('Finished: ').rstrip('.')}"
                        stop = update.get("stop_reason") or stop
            except GraphRecursionError:
                stop = f"recursion_limit={recursion_limit}"
            trail, observations = session.trail, session.observations
    except SessionError as error:
        return AgentRun(stop=f"session error: {error}", seconds=round(time.monotonic() - started, 1))
    return AgentRun(stop=stop, explanation=explanation, answers=answers, trail=trail, observations=observations,
                    seconds=round(time.monotonic() - started, 1))

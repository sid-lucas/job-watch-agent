"""State of the list agent graph: the data every node reads, and how node updates are merged.

A node returns a partial update (only the fields it changes). Fields without a reducer are
replaced by the new value; fields with a reducer (Annotated[type, reducer]) are merged with
reducer(old, new). Live resources (the browser session) and budget limits are not state:
tools hold the session, limits are in config.py.
"""
import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

StopReason = Literal["finished", "llm_budget", "no_new_content", "navigation_refused", "error"]


class ListAgentState(TypedDict):
    # Input, set once at the start
    company: str
    start_url: str
    # Conversation read by the LLM. add_messages appends, or replaces a message with the same id
    messages: Annotated[list[AnyMessage], add_messages]
    # Budget and stop counters, written by code only (replaced at each update)
    llm_calls: int
    clicks_without_new_content: int     # consecutive pagination clicks whose observation brought no line never seen
    click_to_check: bool                # a pagination click was done: its next observation is checked
    # None while running; set once, by code, when the agent stops
    stop_reason: StopReason | None
    # Agent decisions (the browser events stay in BrowserSession.trail). operator.add appends lists
    trail: Annotated[list[str], operator.add]


def initial_state(company: str, start_url: str) -> ListAgentState:
    return ListAgentState(company=company, start_url=start_url, messages=[], llm_calls=0,
                          clicks_without_new_content=0, click_to_check=False, stop_reason=None, trail=[])

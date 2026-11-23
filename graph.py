from langgraph.graph import StateGraph, START, END

from nodes import fetch_rss
from state import JobState


def build_graph():
    """Build and compile the job-watch graph."""
    builder = StateGraph(JobState)

    # Nodes
    builder.add_node("fetch_rss", fetch_rss)

    # Edges
    builder.add_edge(START, "fetch_rss")
    builder.add_edge("fetch_rss", END)

    return builder.compile()
from langgraph.graph import StateGraph, START, END

from nodes import fetch_rss, filter_keywords
from state import JobState


def build_graph():
    """Build and compile the job-watch graph."""
    builder = StateGraph(JobState)

    # Nodes
    builder.add_node("fetch_rss", fetch_rss)
    builder.add_node("filter_keywords", filter_keywords)   # 2. register it

    # Edges
    builder.add_edge(START, "fetch_rss")
    builder.add_edge("fetch_rss", "filter_keywords")
    builder.add_edge("filter_keywords", END)

    return builder.compile()
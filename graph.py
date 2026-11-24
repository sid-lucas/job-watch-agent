from langgraph.graph import StateGraph, START, END

from nodes import fetch_rss, filter_keywords, deduplicate, apply_flags
from state import JobState


def build_graph():
    """Build and compile the job-watch graph."""
    builder = StateGraph(JobState)

    # Nodes
    builder.add_node("fetch_rss", fetch_rss)
    builder.add_node("filter_keywords", filter_keywords)
    builder.add_node("deduplicate", deduplicate)
    builder.add_node("apply_flags", apply_flags)

    # Edges
    builder.add_edge(START, "fetch_rss")
    builder.add_edge("fetch_rss", "filter_keywords")
    builder.add_edge("filter_keywords", "deduplicate")
    builder.add_edge("deduplicate", "apply_flags")
    builder.add_edge("apply_flags", END)

    return builder.compile()
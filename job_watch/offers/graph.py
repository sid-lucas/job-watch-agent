from langgraph.graph import StateGraph, START, END

from job_watch.offers.career_sites import fetch_career_sites
from job_watch.offers.nodes import fetch_rss, triage_rss, deduplicate, score_offers, save_results
from job_watch.offers.state import JobState


def build_graph():
    """Build and compile the job-watch graph."""
    builder = StateGraph(JobState)

    # Nodes
    builder.add_node("fetch_rss", fetch_rss)
    builder.add_node("fetch_career_sites", fetch_career_sites)
    builder.add_node("triage_rss", triage_rss)
    builder.add_node("deduplicate", deduplicate)
    builder.add_node("score_offers", score_offers)
    builder.add_node("save_results", save_results)

    # Edges
    builder.add_edge(START, "fetch_rss")
    builder.add_edge("fetch_rss", "triage_rss")
    builder.add_edge("triage_rss", "fetch_career_sites")
    builder.add_edge("fetch_career_sites", "deduplicate")
    builder.add_edge("deduplicate", "score_offers")
    builder.add_edge("score_offers", "save_results")
    builder.add_edge("save_results", END)

    return builder.compile()
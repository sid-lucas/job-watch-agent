from typing import TypedDict


class Offer(TypedDict):
    """One job offer, normalized from any source."""
    title: str
    company: str
    location: str        # "unknown" when the source does not provide it
    description: str     # plain text, HTML removed
    source: str          # e.g. "swissdevjobs"
    link: str            # tracking parameters removed
    published: str       # publication date from the source
    fetched: str         # date the offer was collected


class JobState(TypedDict):
    """State shared by all nodes of the graph."""
    offers: list[Offer]
    
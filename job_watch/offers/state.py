from typing import TypedDict, NotRequired


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

    # Filled by apply_flags
    score: NotRequired[int]
    reasons: NotRequired[list[str]]   # why the score is what it is
    status: NotRequired[str]          # "new" or "rejected"


class JobState(TypedDict):
    """State shared by all nodes of the graph."""
    offers: list[Offer]
    new_links: NotRequired[list[str]]   # links of offers stored for the first time
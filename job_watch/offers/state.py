from typing import TypedDict, NotRequired


class Offer(TypedDict):
    """One job offer, normalized from any source."""
    key: str             # unique within the company: "url:<link>" for RSS, offer key for career sites
    title: str
    company: str
    location: str        # "unknown" when the source does not provide it
    description: str     # plain text, HTML removed
    source: str          # e.g. "swissdevjobs", or "career_site"
    link: str            # tracking parameters removed; may be empty for a career-site offer
    published: str       # publication date from the source
    fetched: str         # date the offer was collected

    # Career-site offers only
    list_url: NotRequired[str]                  # job list where the offer was seen
    detail_summary: NotRequired[str]
    requirements: NotRequired[list[str]]
    contract: NotRequired[str]
    workload: NotRequired[str]
    ad_language: NotRequired[str]
    required_languages: NotRequired[list[str]]

    # Filled by apply_flags
    score: NotRequired[int]
    reasons: NotRequired[list[str]]   # why the score is what it is
    status: NotRequired[str]          # "new" or "rejected"


class JobState(TypedDict):
    """State shared by all nodes of the graph."""
    offers: list[Offer]
    new_offers: NotRequired[list[tuple[str, str]]]  # (company, key) of offers stored for the first time
    # Career-site collections (list_agent.collect.CompanyCollection), written to listed_offers by
    # save_results in the same transaction as the offers
    collections: NotRequired[list]
    # Run options
    sources: NotRequired[list[str]]         # "rss", "career_sites" (default: both)
    companies: NotRequired[list[str]]       # career sites: only these registry companies (default: all)
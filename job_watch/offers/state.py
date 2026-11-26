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

    # Triage (offers.triage): RSS and career-site offers
    domain: NotRequired[str | None]
    category: NotRequired[str | None]
    secondary_category: NotRequired[str | None]

    # Career-site offers only: list URL
    list_url: NotRequired[str]

    # Criteria answered by the LLM (offers/scoring.py): raw answers, checked again in code each time
    criteria_questions: NotRequired[str]            # fingerprint of the questions answered
    criteria_answers: NotRequired[list[dict] | None]    # None: every model failed
    criteria_model: NotRequired[str]
    full_ad: NotRequired[bool]                      # the answers read the whole ad (offer page)

    # Filled by score_offers (offers/nodes.py)
    score: NotRequired[int]
    reasons: NotRequired[list[str]]   # criteria that counted with points and quotes, or those that rejected
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
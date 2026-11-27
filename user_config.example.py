"""Personal settings template. Copy this file to user_config.py and edit it."""

# Display
MIN_SCORE = 20
MAX_DISPLAY = 10

# Target companies: their career sites are searched and read (registry). For each one, all optional:
#   "tier": a name used by the "company_tier" code criteria below (e.g. "top", "good");
#   "aliases": other names of the same company (searched once, matched as the company);
#   "domains": its domains that do not carry its name (e.g. "ge.ch" for the State of Geneva);
#   "context": a few words for the page judge, when the name is shared with other organisations.
COMPANIES = {
    "Example Bank": {"tier": "top", "aliases": ["Example Bank SA"]},
    "Example Security Company": {"tier": "top"},
    "Example Consulting": {"tier": "good", "domains": ["exco.ch"]},
    "Example Group": {"context": "Swiss holding of watch brands"},
}

# Domains of the triage kept (the others are set aside before any page is opened). Known domains:
# "Technology/IT", "Engineering & R&D (non-IT)", "Finance, banking & accounting",
# "Sales, marketing & communication", "HR, legal & administration", "Operations, production & logistics",
# "Healthcare & humanitarian", "Security & safety (physical)", "Education & training", "Other".
# Keep "Other" (the title gives no clue): an offer is never set aside on what is not known.
KEPT_DOMAINS = ["Technology/IT", "Other"]

# RSS feeds of job offers. "triage": the domain triage runs on their new offers (one cheap LLM call per
# batch); False for a feed that only lists jobs of the kept domains (an IT job board): the criteria decide.
# The feed format read is the one of swissdevjobs.ch ("Position @ Company [Salary]" titles).
RSS_FEEDS = [
    {"name": "swissdevjobs", "url": "https://swissdevjobs.ch/rss", "triage": False},
]

# Short text about you, given to the LLM as context when it answers the criteria. It is sent to
# cloud models: keep it short and never put personal documents (CV, letters) in it.
PROFILE = "Recent graduate in computer science, looking for an entry-level IT job."

# Questions answered by the LLM for each offer: yes, no or unknown, with a quote of the ad as evidence
# (a "yes" whose quote is not found in the ad counts as unknown). Each one has either "reject": True
# (a "yes" rejects the offer) or "points": N. Criteria sharing a "group" are exclusive: only the best
# "yes" of the group counts. "absence": True: the answer is the absence of something in the ad, so a
# "yes" needs no quote; it counts only when the full ad was read. Unknown never rejects, never gives points.
# Write every instruction in the question itself: comments are never sent to the LLM.
# "label" (optional, at most 50 characters): the short name shown with the reasons, instead of the question.
CRITERIA = [
    {"ask": "Is the main workplace outside Switzerland?", "reject": True, "label": "abroad"},
    {"ask": "Is it a senior, lead or principal position?", "reject": True, "label": "senior"},
    {"ask": "Is the job about cybersecurity?", "points": 30, "group": "job type", "label": "security"},
    {"ask": "Is the job about software development?", "points": 20, "group": "job type", "label": "software"},
    {"ask": "Is the position explicitly junior, graduate or entry-level?", "points": 20, "label": "entry level"},
    {"ask": "Does the full ad mention no experience requirement at all?", "points": 10, "absence": True,
     "label": "no experience asked"},
    {"ask": "Is the main workplace in Geneva or Lausanne?", "points": 15, "label": "Geneva or Lausanne"},
    {"ask": "Is it an internship?", "points": -10, "label": "internship"},
]

# Criteria checked by code, without any LLM: "company_tier" (the company, or one of its aliases, is a
# COMPANIES entry of that tier; whole names, case-insensitive) and "posted_older_than_days".
# Same "reject" / "points" / "group" keys as CRITERIA.
CODE_CRITERIA = [
    {"type": "company_tier", "tier": "top", "points": 20, "group": "company"},
    {"type": "company_tier", "tier": "good", "points": 10, "group": "company"},
    {"type": "posted_older_than_days", "days": 30, "points": -5},
]

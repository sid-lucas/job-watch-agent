"""Personal settings template. Copy this file to user_config.py and edit it."""

# Display
MIN_SCORE = 20
MAX_DISPLAY = 10

# Verification
MIN_VERIFY_SCORE = 30
MAX_VERIFY_PER_RUN = 10

# Target companies, in two tiers
TOP_COMPANIES = ["Example Bank", "Example Security Company"]
GOOD_COMPANIES = ["Example Consulting"]

# Domains owned by a company when its name does not appear in them (canonical name -> domains)
COMPANY_DOMAINS = {}

# Alternative names of the same company (canonical name -> aliases), searched only once
COMPANY_ALIASES = {}

# Short description of a company, for names shared with other organisations (used by the page judge)
COMPANY_CONTEXT = {}

# Domains of the triage kept (the others are set aside before any page is opened). Known domains:
# "Technology/IT", "Engineering & R&D (non-IT)", "Finance, banking & accounting",
# "Sales, marketing & communication", "HR, legal & administration", "Operations, production & logistics",
# "Healthcare & humanitarian", "Security & safety (physical)", "Education & training", "Other".
# Keep "Other" (the title gives no clue): an offer is never set aside on what is not known.
KEPT_DOMAINS = ["Technology/IT", "Other"]

# Short text about you, given to the LLM as context when it answers the criteria. It is sent to
# cloud models: keep it short and never put personal documents (CV, letters) in it.
PROFILE = "Recent graduate in computer science, looking for an entry-level IT job."

# Questions answered by the LLM for each offer: yes, no or unknown, with a quote of the ad as evidence
# (a "yes" whose quote is not found in the ad counts as unknown). Each one has either "reject": True
# (a "yes" rejects the offer) or "points": N. Criteria sharing a "group" are exclusive: only the best
# "yes" of the group counts. "absence": True: the answer is the absence of something in the ad, so a
# "yes" needs no quote; it counts only when the full ad was read. Unknown never rejects, never gives points.
# Write every instruction in the question itself: comments are never sent to the LLM.
CRITERIA = [
    {"ask": "Is the job located outside Switzerland?", "reject": True},
    {"ask": "Is it a senior, lead or principal position?", "reject": True},
    {"ask": "Is the job about cybersecurity?", "points": 30, "group": "job type"},
    {"ask": "Is the job about software development?", "points": 20, "group": "job type"},
    {"ask": "Is the position explicitly junior, graduate or entry-level?", "points": 20},
    {"ask": "Does the full ad mention no experience requirement at all?", "points": 10, "absence": True},
    {"ask": "Is the job in Geneva or Lausanne?", "points": 15},
    {"ask": "Is it an internship?", "points": -10},
]

# Criteria checked by code, without any LLM: "company_in" (whole names, case-insensitive) and
# "posted_older_than_days". Same "reject" / "points" / "group" keys as CRITERIA.
CODE_CRITERIA = [
    {"type": "company_in", "names": TOP_COMPANIES, "points": 20, "group": "company"},
    {"type": "company_in", "names": GOOD_COMPANIES, "points": 10, "group": "company"},
    {"type": "posted_older_than_days", "days": 30, "points": -5},
]

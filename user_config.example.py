"""Personal settings template. Copy this file to user_config.py and edit it."""
from job_watch.checks import is_german_ad, names_pattern

# Display
MIN_SCORE = 20
MAX_DISPLAY = 10

# Verification
MIN_VERIFY_SCORE = 30
MAX_VERIFY_PER_RUN = 10

# Keyword filter (whole words, case-insensitive)
KEYWORDS = ["security", "cyber", "soc", "siem", "pentest"]

# Target companies, in two tiers
TOP_COMPANIES = ["Example Bank", "Example Security Company"]
GOOD_COMPANIES = ["Example Consulting"]

# Reject rules: an offer is rejected if the rule matches (regex "pattern" or "check" function)
REJECT_RULES = [
    {"name": "senior title", "field": "title",
     "pattern": r"\b(senior|lead|principal|head of|manager|director)\b"},
    {"name": "german ad", "field": "description", "check": is_german_ad},
]

# Score rules: points added (or removed) when the pattern matches the field
SCORE_RULES = [
    {"name": "security title", "field": "title", "points": 30,
     "pattern": r"\b(security|cyber|soc)\b"},
    {"name": "entry-level", "field": "title", "points": 30,
     "pattern": r"\b(junior|graduate|trainee)\b"},
    {"name": "top company", "field": "company", "points": 20,
     "pattern": names_pattern(TOP_COMPANIES)},
    {"name": "good company", "field": "company", "points": 10,
     "pattern": names_pattern(GOOD_COMPANIES)},
]
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

# Rules on the facts of an offer, applied by code only (never sent to an LLM). Without these two
# lists, the defaults of job_watch/config.py apply. A rule tests one fact with one operator:
#   is, in, not_in, contains (list facts), above, below (numbers), matches (regular expression),
#   in_names (whole names, e.g. companies).
# Facts (job_watch/offers/rules.py, FACTS): domain, category, secondary_category, title, company, source,
#   location (switzerland/abroad/unknown), city, country, seniority (graduate/junior/mid/senior/lead),
#   experience_years, experience_years_required, languages_required, languages_nice (en/fr/de/it),
#   contract (permanent/fixed_term/internship/apprenticeship), workload, salary,
#   education (CFC/ES/HES-university), ad_language.
# An unknown fact never rejects an offer and never gives points. Run `python -m scripts.rescore`
# after a change: rejections and scores are computed again without any LLM call.
#
# SECURITY = ["Cybersecurity SOC/incident response", "Cybersecurity GRC/risk/compliance",
#             "Cybersecurity engineering/architecture/pentest", "AI security"]
#
# DEALBREAKERS = [
#     {"name": "abroad", "fact": "location", "is": "abroad"},
#     {"name": "senior level", "fact": "seniority", "in": ["senior", "lead"]},
#     {"name": "German required", "fact": "languages_required", "contains": "de"},
#     {"name": "more than 5 years required", "fact": "experience_years_required", "above": 5},
#     {"name": "ad in German", "fact": "ad_language", "is": "de"},
# ]
#
# BONUSES = [
#     {"name": "security job", "fact": "category", "in": SECURITY, "points": 30},
#     {"name": "AI/ML job", "fact": "category", "is": "AI/ML/data science", "points": 30},
#     {"name": "entry level", "fact": "seniority", "in": ["graduate", "junior"], "points": 30},
#     {"name": "target city", "fact": "city", "matches": r"gen[eè]v|geneva|genf|lausanne", "points": 20},
#     {"name": "top company", "fact": "company", "in_names": TOP_COMPANIES, "points": 20},
#     {"name": "good company", "fact": "company", "in_names": GOOD_COMPANIES, "points": 10},
#     {"name": "internship", "fact": "contract", "is": "internship", "points": -10},
# ]

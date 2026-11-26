"""Technical settings. Personal settings are in user_config.py (see user_config.example.py)."""
from pathlib import Path
try:
    import user_config  # noqa: F401
except ModuleNotFoundError:
    raise SystemExit("Missing user_config.py: copy user_config.example.py to user_config.py and edit it.")

from user_config import (
    MIN_SCORE, MAX_DISPLAY, MIN_VERIFY_SCORE, MAX_VERIFY_PER_RUN,
    KEYWORDS, TOP_COMPANIES, GOOD_COMPANIES, COMPANY_ALIASES, COMPANY_DOMAINS, COMPANY_CONTEXT,
    REJECT_RULES, SCORE_RULES,
)

# Paths
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "offers.db"
REGISTRY_PATH = BASE_DIR / "data" / "career_sites.json"

# LLM chains for public web data, one per task, tried in order: (provider, model).
# Mistral is ignored without MISTRAL_API_KEY.
CLOUD_MODELS = [
    ("gemini", "gemini-3.5-flash-lite"),
    ("gemini", "gemini-3.1-flash-lite"),
]
# Triage: short titles in batches, the local model first (no quota), the cloud as fallback
TRIAGE_CHAIN = [("ollama", "qwen3:8b"), *CLOUD_MODELS]
# Reading pages (list extraction, offer detail, page judge): long text, structured output
DETAIL_CHAIN = [*CLOUD_MODELS, ("mistral", "mistral-small-latest"), ("ollama", "qwen3:8b")]
# List agent: tool calling
NAVIGATION_CHAIN = [*CLOUD_MODELS, ("mistral", "mistral-small-latest"), ("ollama", "qwen3:8b")]
# Offers per triage call, by provider of the first model of the chain: the local model is more
# reliable one title at a time, cloud models handle a batch
TRIAGE_BATCH_SIZE = {"ollama": 1, "gemini": 25, "mistral": 25, "default": 10}
OLLAMA_THINK = False     # qwen3 reasoning ("thinking"): slower; off by default
# Domains of offers.triage kept by the listing filter (an offer without a valid answer is kept)
KEPT_DOMAINS = ["Technology/IT"]
OLLAMA_NUM_CTX = 24576   # context size in tokens; fits a 30000-character page in 11 GB of VRAM

# RSS source
FEED_URL = "https://swissdevjobs.ch/rss"
SOURCE_NAME = "swissdevjobs"

# Web access
USER_AGENT = "job-watch/0.1 (personal job search project)"
MAX_PAGE_CHARS = 8000   # page text is truncated to this size
# List agent budgets, enforced in code (the agent's own stop reason is not trusted)
AGENT_MAX_LLM_CALLS = 50                  # agent turns per job list (UBS, 13 pages: about 30)
AGENT_MAX_CLICKS_WITHOUT_NEW_CONTENT = 3  # consecutive pagination clicks that bring no line never seen
MAX_DETAIL_PAGES = 20   # offer pages opened per career-site run (detail phase)
DETAIL_PAUSE_SECONDS = 2     # pause between two offer pages, out of politeness to the site
DETAIL_MAX_CHARS = 20000     # raw text kept per offer page (for the detail extraction and V2)
ROBOTS_TIMEOUT = 10     # seconds

# Domains never fetched, whatever their robots.txt says (terms of use forbid automated access)
BLOCKED_DOMAINS = ["jobs.ch", "jobup.ch", "jobscout24.ch", "linkedin.com", "indeed.com"]
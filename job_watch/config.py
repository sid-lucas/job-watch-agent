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

# LLM chain for public web data, tried in order: (provider, model)
LLM_CHAIN = [
    ("gemini", "gemini-3.5-flash-lite"),
    ("gemini", "gemini-3.1-flash-lite"),
    ("ollama", "qwen3:8b"),
]
OLLAMA_NUM_CTX = 24576   # context size in tokens; fits a 30000-character page in 11 GB of VRAM

# RSS source
FEED_URL = "https://swissdevjobs.ch/rss"
SOURCE_NAME = "swissdevjobs"

# Web access
USER_AGENT = "job-watch/0.1 (personal job search project)"
MAX_PAGE_CHARS = 8000   # page text is truncated to this size
MAX_DETAIL_PAGES = 20   # offer pages opened per career-site run (detail phase)
DETAIL_PAUSE_SECONDS = 2     # pause between two offer pages, out of politeness to the site
DETAIL_MAX_CHARS = 20000     # raw text kept per offer page (for the detail extraction and V2)
ROBOTS_TIMEOUT = 10     # seconds

# Domains never fetched, whatever their robots.txt says (terms of use forbid automated access)
BLOCKED_DOMAINS = ["jobs.ch", "jobup.ch", "jobscout24.ch", "linkedin.com", "indeed.com"]
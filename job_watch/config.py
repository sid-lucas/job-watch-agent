"""Technical settings. Personal settings are in user_config.py (see user_config.example.py)."""
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "offers.db"

# RSS source
FEED_URL = "https://swissdevjobs.ch/rss"
SOURCE_NAME = "swissdevjobs"

# Verification LLM (public data only, so a cloud model is acceptable)
VERIFY_MODEL = "gemini-3.5-flash-lite"

# Web access
USER_AGENT = "job-watch/0.1 (personal job search project)"
MAX_PAGE_CHARS = 8000   # page text is truncated to this size
ROBOTS_TIMEOUT = 10     # seconds

# Domains never fetched, whatever their robots.txt says (terms of use forbid automated access)
BLOCKED_DOMAINS = ["jobs.ch", "jobup.ch", "jobscout24.ch", "linkedin.com", "indeed.com"]

# Personal settings
try:
    from user_config import (
        MIN_SCORE, MAX_DISPLAY, MIN_VERIFY_SCORE, MAX_VERIFY_PER_RUN,
        KEYWORDS, TOP_COMPANIES, GOOD_COMPANIES, REJECT_RULES, SCORE_RULES,
    )
except ImportError:
    raise SystemExit("Missing user_config.py: copy user_config.example.py to user_config.py and edit it.")
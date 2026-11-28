"""Technical settings. Personal settings are in user_config.py (see user_config.example.py)."""
from pathlib import Path
try:
    import user_config
except ModuleNotFoundError:
    raise SystemExit("Missing user_config.py: copy user_config.example.py to user_config.py and edit it.")

from user_config import (
    MIN_SCORE, MAX_DISPLAY,
    COMPANIES, PROFILE, CRITERIA, CODE_CRITERIA, KEPT_DOMAINS, RSS_FEEDS,
)
from job_watch.offers.criteria import load_settings

# Criteria of the user, validated at startup (a problem stops the program with a clear message)
SETTINGS = load_settings(PROFILE, CRITERIA, CODE_CRITERIA, KEPT_DOMAINS, RSS_FEEDS, COMPANIES)

# Paths
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "offers.db"
REGISTRY_PATH = BASE_DIR / "data" / "career_sites.json"

# LLM chain for public web data, the same for every task (triage, list extraction, list agent,
# criteria, page judge): tried in order, the first one is the preferred one. (provider, model, enabled).
# Free tiers only; quotas per model on the Gemini API (AI Studio, Rate limits). A daily quota spent
# skips that model for the rest of the run; a per-minute limit (requests or tokens) is waited for.
MODEL_CHAIN = [
    ("gemini", "gemini-3.5-flash-lite", True),      # 500 requests per day
    ("gemini", "gemini-3.1-flash-lite", True),      # 500 per day
    ("gemini", "gemini-3.8-flash", True),           # 20 per day
    ("gemini", "gemini-3.6-flash", True),           # 20 per day
    ("gemini", "gemini-3-flash-preview", True),     # 20 per day
    ("gemini", "gemini-4-hydrogen", True),          # 20 per day
    ("mistral", "mistral-small-latest", False),     # free tier not active
    ("ollama", "qwen3:8b", True),                   # local, last resort
]
LOCAL_PROVIDERS = {"ollama"}
# When only local models are left (every cloud model skipped for the run), at most this many offers
# are still answered by the criteria during the run; the others wait for the next run (they stay new)
LOCAL_ONLY_MAX_CRITERIA = 5
# Offers per triage call, by model ("provider:model"), else by provider, of the model that answers
# (a batch passed to the next model of the chain is split again with that model's size)
TRIAGE_BATCH_SIZE = {"gemini": 25, "mistral": 25, "ollama": 10, "default": 10}
OLLAMA_THINK = False     # qwen3 reasoning ("thinking"): slower; off by default
OLLAMA_NUM_CTX = 24576   # context size in tokens; fits a 30000-character page in 11 GB of VRAM

# Matching against the profile (step 2): personal data, local models only. llm.local_models() stops
# the program if this chain holds a cloud model. The profile is read only at run time, on this computer.
PROFILE_PATH = BASE_DIR / "data" / "personal" / "profile.md"
MATCH_CHAIN = [
    ("ollama", "qwen3:8b", True),
]
# Reasoning for the matching tasks. With structured output in the same call, qwen3 gave unstable
# lists (empty once, several requirements merged); so with MATCH_THINK, one call reasons in free
# text, a second call without reasoning only puts that draft in the schema.
MATCH_THINK = True

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
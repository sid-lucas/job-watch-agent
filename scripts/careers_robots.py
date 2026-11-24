import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.append(str(Path(__file__).parent.parent))  # allow imports from the project root

import config
from search import search_offer
from web import can_fetch

allowed_count = 0
blocked_count = 0

for company in config.TOP_COMPANIES + config.GOOD_COMPANIES:
    results = search_offer(company, "careers jobs Switzerland", max_results=3)
    print(f"\n{company}")
    for r in results:
        allowed = can_fetch(r["link"])
        allowed_count += allowed
        blocked_count += not allowed
        domain = urlsplit(r["link"]).netloc
        print(f"  {'ALLOWED' if allowed else 'BLOCKED'}  {domain:35s} {r['link'][:80]}")

print(f"\nTotal: {allowed_count} allowed, {blocked_count} blocked")
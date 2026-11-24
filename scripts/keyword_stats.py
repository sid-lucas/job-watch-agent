import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))  # allow imports from the project root

from job_watch import config
from job_watch.nodes import fetch_rss

offers = fetch_rss({"offers": []})["offers"]

# Count how many offers each keyword matches
stats = []
for keyword in config.KEYWORDS:
    pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
    count = sum(1 for o in offers if pattern.search(f"{o['title']} {o['description']}"))
    stats.append((count, keyword))

for count, keyword in sorted(stats, reverse=True):
    if count > 0:
        print(f"{count:4d}  {keyword}")
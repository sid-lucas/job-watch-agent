import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))  # allow imports from the project root

from checks import GERMAN_STOPWORDS
from nodes import fetch_rss, filter_keywords

offers = filter_keywords(fetch_rss({"offers": []}))["offers"]

# German stopword ratio for each offer, highest first
rows = []
for o in offers:
    words = re.findall(r"\b\w+\b", o["description"].lower())
    ratio = sum(w in GERMAN_STOPWORDS for w in words) / len(words) if words else 0
    rows.append((ratio, o["title"]))

for ratio, title in sorted(rows, reverse=True):
    print(f"{ratio:6.1%}  {title[:70]}")
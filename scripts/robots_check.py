import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))  # allow imports from the project root

from web import can_fetch

URLS = [
    # Reference: blocked
    "https://jobs-ch.kpmg.com/?lang=en",
    # Top companies
    "https://www.pictet.com/careers",
    "https://www.lombardodier.com/home/careers.html",
    "https://ubp.com/en/about-us/careers/job-offers",
    "https://www.juliusbaer.com/en/careers/faq",
    "https://proton.me/careers",
    "https://job-boards.eu.greenhouse.io/proton",
]

for url in URLS:
    print(f"{'ALLOWED' if can_fetch(url) else 'BLOCKED'}  {url}")
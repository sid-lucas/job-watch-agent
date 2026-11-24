import feedparser

from job_watch import config

feed = feedparser.parse(config.FEED_URL)
print(f"Number of offers: {len(feed.entries)}")

# Inspect the first offer
first = feed.entries[0]
print("\nAvailable fields:", list(first.keys()))
print("\nTitle:", first.title)
print("Link:", first.link)
print("Published:", first.get("published"))
print("\nFull description:", first.get("description", ""))
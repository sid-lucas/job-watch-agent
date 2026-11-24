import os

import requests
from dotenv import load_dotenv

load_dotenv()

SERPER_URL = "https://google.serper.dev/search"


def search_offer(company: str, title: str, max_results: int = 5) -> list[dict]:
    """Search the web for a job offer. Return a list of {title, link, snippet}."""
    response = requests.post(
        SERPER_URL,
        headers={"X-API-KEY": os.environ["SERPER_API_KEY"]},
        json={"q": f"{company} {title}", "gl": "ch", "num": max_results},
        timeout=15,
    )
    response.raise_for_status()

    results = []
    for item in response.json().get("organic", []):
        results.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return results
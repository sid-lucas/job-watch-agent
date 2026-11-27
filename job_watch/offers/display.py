"""Printing of stored or new offers, shared by main.py and scripts/show_offers.py."""
from urllib.parse import quote_plus


def search_link(offer: dict) -> str:
    """Build a web search link to find the offer on the company's own site."""
    return "https://www.google.com/search?q=" + quote_plus(f"{offer['company']} {offer['title']}")


def print_offer(offer: dict) -> None:
    """Score, title, reasons with their quotes, location and links of one offer."""
    print(f"\n{offer['score']:4d}  {offer['title']} @ {offer['company']}  [{offer['source']}]")
    for reason in offer["reasons"]:
        print(f"      {reason}")
    if offer.get("location") and offer["location"] != "unknown":
        print(f"      Location: {offer['location']}")
    if offer["link"]:
        print(f"            Offer:  {offer['link']}")
    else:
        print(f"            List:   {offer.get('list_url', '-')}  (no own link for this offer)")
    print(f"            Search: {search_link(offer)}")

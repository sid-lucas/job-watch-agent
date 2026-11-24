"""Headless browser access: render a page (JavaScript included) and list its links."""
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from job_watch import config, web

RENDER_WAIT_MS = 3000       # extra time for JavaScript to build the page after load
PAGE_TIMEOUT_MS = 30000


def page_links(url: str) -> list[str]:
    """Return the absolute URLs of the links and iframes of a rendered page.

    Return an empty list if robots.txt forbids the page or if it fails to load.
    """
    if not web.can_fetch(url):
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=config.USER_AGENT)
            page.goto(url, wait_until="load", timeout=PAGE_TIMEOUT_MS)
            page.wait_for_timeout(RENDER_WAIT_MS)
            links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            frames = page.eval_on_selector_all("iframe[src]", "els => els.map(e => e.src)")
        except PlaywrightError:
            return []
        finally:
            browser.close()

    # Keep web links only, without duplicates, in page order
    seen, result = set(), []
    for link in links + frames:
        if link.startswith(("http://", "https://")) and link not in seen:
            seen.add(link)
            result.append(link)
    return result
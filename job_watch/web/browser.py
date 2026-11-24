"""Headless browser access: render a page (JavaScript included), get its text and links."""
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from job_watch import config
from job_watch.web import access as web

RENDER_WAIT_MS = 3000       # extra time for JavaScript to build the page after load
PAGE_TIMEOUT_MS = 30000

LINKS_JS = "els => els.map(e => ({text: (e.innerText || '').trim(), url: e.href}))"
FRAMES_JS = "els => els.map(e => ({text: 'iframe', url: e.src}))"


def render_page(url: str) -> dict | None:
    """Render a page and return {url, text, links}, or None if forbidden or failed.

    url is the final URL after redirects; links are {text, url} with absolute URLs.
    """
    if not web.can_fetch(url):
        return None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=config.USER_AGENT)
            # "load" waits for every resource and can time out on heavy pages that are already usable
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            page.wait_for_timeout(RENDER_WAIT_MS)
            final_url = page.url
            text = page.inner_text("body")
            links = page.eval_on_selector_all("a[href]", LINKS_JS)
            frames = page.eval_on_selector_all("iframe[src]", FRAMES_JS)
        except PlaywrightError:
            return None
        finally:
            browser.close()

    # Keep web links only, without duplicates, in page order
    seen, unique_links = set(), []
    for link in links + frames:
        if link["url"].startswith(("http://", "https://")) and link["url"] not in seen:
            seen.add(link["url"])
            unique_links.append({"text": link["text"][:100], "url": link["url"]})

    return {"url": final_url, "text": text[:config.MAX_PAGE_CHARS], "links": unique_links}


def page_links(url: str) -> list[str]:
    """Return the absolute URLs of the links and iframes of a rendered page."""
    page = render_page(url)
    return [link["url"] for link in page["links"]] if page else []
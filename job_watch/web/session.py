"""Persistent browser session for the list agent: guarded navigation and numbered observations.

Every document request (main frame and iframes) must be GET and allowed by robots.txt
(access.can_fetch); main-frame navigations must also stay on the host of the start URL.
Sub-requests (XHR, scripts, images, styles) are not filtered, as in render_page.
"""
import time
from typing import Literal
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Route, Request, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel

from job_watch import config
from job_watch.web import access
from job_watch.web.browser import LOAD_WAIT_MS, PAGE_TIMEOUT_MS, RENDER_WAIT_MS

MAX_TEXT_CHARS = 30000      # page text kept per observation
MAX_ELEMENTS = 300          # numbered controls kept per observation, in page order
ID_ATTR = "data-jw-id"      # attribute set by the harness on each numbered control

# Visible controls a click could target. Text inputs are never listed: there is no typing tool.
ELEMENTS_JS = """
([attr, max]) => {
  document.querySelectorAll(`[${attr}]`).forEach(e => e.removeAttribute(attr));
  const selector = 'a[href], button, [role="button"], [role="link"], [role="tab"], '
                 + 'input[type="button"], input[type="submit"]';
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  const elements = [];
  let truncated = false;
  for (const e of document.querySelectorAll(selector)) {
    if (!e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
    const box = e.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) continue;
    if (elements.length >= max) { truncated = true; break; }
    const id = elements.length + 1;
    e.setAttribute(attr, String(id));
    const tag = e.tagName.toLowerCase();
    const labelledBy = clean((e.getAttribute('aria-labelledby') || '').split(/\\s+/)
      .map(i => document.getElementById(i)?.innerText || '').join(' '));
    // Approximation of the accessible name
    const name = clean(e.getAttribute('aria-label')) || labelledBy || clean(e.innerText)
              || clean(e.getAttribute('title')) || clean(e.value) || clean(e.getAttribute('alt'));
    const form = e.closest('form');
    elements.push({
      id, tag, name: name.slice(0, 120),
      role: e.getAttribute('role') || (tag === 'a' ? 'link' : 'button'),
      href: tag === 'a' ? e.href : null,
      in_form: !!form,
      form_has_inputs: !!form && !!form.querySelector(
        'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select'),
    });
  }
  return {elements, truncated};
}
"""


def site_host(url: str) -> str:
    """Host of a URL, lower case, without a leading 'www.' (bcn.ch = www.bcn.ch)."""
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


class Element(BaseModel):
    id: int
    role: str
    name: str
    tag: str
    href: str | None = None
    in_form: bool
    form_has_inputs: bool


class Observation(BaseModel):
    url: str
    title: str
    text: str
    truncated: bool
    elements: list[Element]
    elements_truncated: bool


class TrailEvent(BaseModel):
    seconds: float              # since the session started
    kind: Literal["navigation_allowed", "navigation_refused", "popup_closed",
                  "download_refused", "dialog_dismissed", "observe"]
    detail: str


class SessionError(Exception):
    """The start page could not be opened (refused navigation or load failure)."""


class BrowserSession:
    """One headless page kept open, in an ephemeral context emptied at the end of the session.

        with BrowserSession(url) as session:
            observation = session.observe()
    """

    def __init__(self, start_url: str):
        self.start_url = start_url
        self.allowed_host = site_host(start_url)
        self.trail: list[TrailEvent] = []
        self.last_observation: Observation | None = None
        self._started = time.monotonic()

    # ---------- lifecycle ----------

    def __enter__(self) -> "BrowserSession":
        if not access.can_fetch(self.start_url):
            self._log("navigation_refused", f"start URL not allowed: {self.start_url}")
            raise SessionError(f"start URL not allowed: {self.start_url}")
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context(user_agent=config.USER_AGENT, accept_downloads=False)
            self._context.route("**/*", self._guard)
            self.page = self._context.new_page()
            self.page.on("download", self._on_download)
            self.page.on("dialog", self._on_dialog)
            self._context.on("page", self._on_popup)
            self.page.goto(self.start_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            self._settle()
        except PlaywrightError as error:
            self.__exit__(None, None, None)
            raise SessionError(f"start page failed: {str(error)[:200]}") from error
        return self

    def __exit__(self, *exc_info) -> None:
        for close in ("_context", "_browser"):
            try:
                getattr(self, close).close()
            except (AttributeError, PlaywrightError):
                pass
        if hasattr(self, "_playwright"):
            self._playwright.stop()

    # ---------- observation ----------

    def observe(self) -> Observation:
        """Text of the page and its visible controls, numbered; previous ids become invalid."""
        found = self.page.evaluate(ELEMENTS_JS, [ID_ATTR, MAX_ELEMENTS])
        text = self.page.inner_text("body")
        observation = Observation(
            url=self.page.url,
            title=self.page.title(),
            text=text[:MAX_TEXT_CHARS],
            truncated=len(text) > MAX_TEXT_CHARS,
            elements=[Element(**e) for e in found["elements"]],
            elements_truncated=found["truncated"],
        )
        self.last_observation = observation
        self._log("observe", f"{len(observation.elements)} elements, {len(text)} chars")
        return observation

    # ---------- guards ----------

    def _guard(self, route: Route, request: Request) -> None:
        """Check every document request before it leaves the browser."""
        if request.resource_type != "document":
            route.continue_()
            return
        main_frame = request.frame.parent_frame is None
        frame = "main" if main_frame else "iframe"
        reason = None
        if request.method != "GET":
            reason = f"method {request.method}"
        elif main_frame and site_host(request.url) != self.allowed_host:
            reason = "other host"
        elif not access.can_fetch(request.url):
            reason = "robots.txt or blocked domain"
        if reason:
            self._log("navigation_refused", f"{frame} {request.method} {request.url} ({reason})")
            route.abort()
        else:
            self._log("navigation_allowed", f"{frame} {request.url}")
            route.continue_()

    def _on_popup(self, popup) -> None:
        self._log("popup_closed", popup.url)
        popup.close()

    def _on_download(self, download) -> None:
        self._log("download_refused", download.url)

    def _on_dialog(self, dialog) -> None:
        self._log("dialog_dismissed", f"{dialog.type}: {dialog.message[:100]}")
        dialog.dismiss()

    # ---------- helpers ----------

    def _settle(self) -> None:
        """Wait for the page to be usable, as render_page does."""
        try:
            self.page.wait_for_load_state("load", timeout=LOAD_WAIT_MS)
        except PlaywrightTimeoutError:
            pass    # heavy pages that never fire "load" are used as they are
        self.page.wait_for_timeout(RENDER_WAIT_MS)

    def _log(self, kind: str, detail: str) -> None:
        self.trail.append(TrailEvent(seconds=round(time.monotonic() - self._started, 1), kind=kind, detail=detail))

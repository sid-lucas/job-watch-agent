"""Persistent browser session for the list agent: guarded navigation, numbered observations, guarded clicks.

Every document request (main frame and iframes) must be GET and allowed by robots.txt
(access.can_fetch); main-frame navigations must also stay on the host of the start URL.
Sub-requests (XHR, scripts, images, styles) are not filtered, as in render_page.

Clicks go through click_rules.check() on the observed facts, then through session checks:
the id must come from the last observation, the control must not have changed since, the
click budget must not be spent, and the control must be clickable without force.
"""
import time
from typing import Literal
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame, Route, Request, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel

from job_watch import config
from job_watch.web import access
from job_watch.web.browser import LOAD_WAIT_MS, PAGE_TIMEOUT_MS, RENDER_WAIT_MS
from job_watch.web.click_rules import Control, Purpose, Reason, acceptance_pending, check, site_host
from job_watch.web.new_content import first_changed, new_lines, page_lines

MAX_TEXT_CHARS = 30000      # page text, and new text, kept per observation
MAX_ELEMENTS = 3000         # numbered controls collected per observation, in page order, all frames together
MAX_CLICKS = 30             # clicks per session, refused ones not counted
CLICK_TIMEOUT_MS = 5000     # a control still covered or hidden after this delay is not clicked
CONSENT_MAX_CHARS = 5000    # a floating container longer than this is a page layout, not a consent banner
ID_ATTR = "data-jw-id"      # attribute set by the harness on each numbered control

# Facts of one control, shared by the observation and by the check made just before a click.
# in_consent: the nearest floating ancestor (dialog, aria-modal, fixed or sticky) is short and mentions cookies.
FACTS_JS = r"""
const clean = s => (s || '').replace(/\s+/g, ' ').trim();
const facts = e => {
  const tag = e.tagName.toLowerCase();
  const labelledBy = clean((e.getAttribute('aria-labelledby') || '').split(/\s+/)
    .map(i => document.getElementById(i)?.innerText || '').join(' '));
  const text = clean(e.innerText);
  // Approximation of the accessible name
  const name = clean(e.getAttribute('aria-label')) || labelledBy || text
            || clean(e.getAttribute('title')) || clean(e.value) || clean(e.getAttribute('alt'));
  const form = e.form || e.closest('form');
  // A <button> without type attribute submits its form: report the effective type
  const type = (tag === 'button' && e.form) ? e.type : e.getAttribute('type');
  const base = document.querySelector('base[target]');
  const popup = e.getAttribute('aria-haspopup');
  const expanded = e.getAttribute('aria-expanded');
  const current = e.getAttribute('aria-current');
  let inConsent = false;
  for (let a = e.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
    const position = getComputedStyle(a).position;
    const role = a.getAttribute('role');
    if (a.tagName === 'DIALOG' || role === 'dialog' || role === 'alertdialog'
        || a.getAttribute('aria-modal') === 'true' || position === 'fixed' || position === 'sticky') {
      const content = a.innerText || '';
      inConsent = content.length <= %CONSENT_MAX% && /cookie/i.test(content);
      break;
    }
  }
  return {
    tag, text: text.slice(0, 120), name: name.slice(0, 200),
    role: e.getAttribute('role') || (tag === 'a' ? 'link' : 'button'),
    input_type: type ? type.toLowerCase() : null,
    href: tag === 'a' ? e.href : null,
    target: e.getAttribute('target') || (tag === 'a' && base ? base.getAttribute('target') : null),
    download: e.hasAttribute('download'),
    aria_haspopup: popup !== null && popup !== 'false',
    aria_expanded: expanded === null ? null : expanded === 'true',
    aria_current: current !== null && current !== 'false',
    disabled: e.disabled === true || e.getAttribute('aria-disabled') === 'true',
    in_form: !!form,
    form_has_inputs: !!form && !!form.querySelector(
      'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select'),
    in_consent: inConsent,
  };
};
""".replace("%CONSENT_MAX%", str(CONSENT_MAX_CHARS))

# Visible controls a click could target, numbered from `start`. Text inputs are never listed:
# there is no typing tool. Tabs and checkboxes are listed so that the rules refuse them explicitly.
ELEMENTS_JS = "([attr, max, start]) => {\n" + FACTS_JS + r"""
  document.querySelectorAll(`[${attr}]`).forEach(e => e.removeAttribute(attr));
  const selector = 'a[href], button, [role="button"], [role="link"], [role="tab"], [role="checkbox"], '
                 + 'input[type="button"], input[type="submit"], input[type="checkbox"], input[type="radio"]';
  const elements = [];
  let truncated = false;
  for (const e of document.querySelectorAll(selector)) {
    if (!e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
    const box = e.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) continue;
    if (elements.length >= max) { truncated = true; break; }
    const id = start + elements.length;
    e.setAttribute(attr, String(id));
    elements.push({id, ...facts(e)});
  }
  return {elements, truncated};
}
"""

ONE_ELEMENT_JS = "e => {\n" + FACTS_JS + "\n  return facts(e);\n}"

SessionReason = Literal["stale_id", "budget", "changed", "not_clickable", "cookie_banner_first"]


class Element(Control):
    """A numbered control of the last observation."""
    id: int
    frame: str = "main"         # "main", or the URL of the same-site iframe holding the control


class FrameReport(BaseModel):
    url: str
    observed: bool              # False: other site (or unreadable), its controls are not listed
    elements: int = 0


class Observation(BaseModel):
    url: str
    title: str
    text: str                   # main frame text only
    truncated: bool
    new_text: str               # lines new since the previous observation (all lines the first time)
    new_text_truncated: bool
    new_text_full: str = ""     # the same lines, never cut: read by the offer extractor, never sent to the agent
    new_line_count: int         # 0: nothing new since the previous observation
    elements: list[Element]
    elements_truncated: bool
    iframes: list[FrameReport] = []
    acceptance_fallback: bool = False   # cookie acceptance already allowed on this host (a refusal failed)
    # Elements before this position are unchanged since the previous observation of the same URL
    # (0: show all). Display only: every id stays valid for click().
    changed_from: int = 0


def _facts(element: Element) -> tuple:
    """Comparable facts of an element, without its id (ids are renumbered at each observation)."""
    return tuple(element.model_dump(exclude={"id"}).values())


def changed_from(previous: "Observation | None", url: str, elements: list[Element]) -> int:
    """Position of the first new or changed element, when the rest of the page is unchanged.

    0 (everything is shown) on the first observation, after a URL change (fragment ignored),
    and when no element is new or changed: the agent can then try any control again.
    """
    if previous is None or _without_fragment(previous.url) != _without_fragment(url):
        return 0
    position = first_changed([_facts(e) for e in previous.elements], [_facts(e) for e in elements])
    return position or 0


class ClickResult(BaseModel):
    element_id: int
    purpose: Purpose
    clicked: bool
    reason: Reason | SessionReason | None = None
    detail: str = ""
    url_before: str
    url_after: str
    navigation_refused: bool = False    # a navigation triggered by the click was refused by the guard
    acceptance_fallback: bool = False   # a cookie refusal broke the list: acceptance now allowed on this host


class BackResult(BaseModel):
    done: bool
    reason: Literal["no_list_page", "already_on_list", "budget", "navigation_failed"] | None = None
    detail: str = ""
    url_before: str
    url_after: str


class TrailEvent(BaseModel):
    seconds: float              # since the session started
    kind: Literal["navigation_allowed", "navigation_refused", "popup_closed", "download_refused",
                  "dialog_dismissed", "observe", "click", "click_refused", "cookie_accepted",
                  "cookie_refusal_failed", "returned_to_start", "back_to_list", "back_to_list_refused"]
    detail: str


class SessionError(Exception):
    """The start page could not be opened (refused navigation or load failure)."""


def _without_fragment(url: str) -> str:
    return url.split("#", 1)[0]


class BrowserSession:
    """One headless page kept open, in an ephemeral context emptied at the end of the session.

        with BrowserSession(url) as session:
            observation = session.observe()
            result = session.click(observation.elements[0].id, "pagination")
    """

    def __init__(self, start_url: str, max_clicks: int = MAX_CLICKS, render_wait_ms: int = RENDER_WAIT_MS):
        self.start_url = start_url
        self.allowed_host = site_host(start_url)
        self.max_clicks = max_clicks
        self.render_wait_ms = render_wait_ms
        self.clicks = 0
        self.trail: list[TrailEvent] = []
        self.last_observation: Observation | None = None
        self.observations: list[Observation] = []              # every observation of the session, in order
        self._previous_lines: list[str] = []                   # full text lines of the last observation
        self._elements: dict[int, tuple[Element, Frame]] = {}  # valid ids: last observation, no click since
        self._fallback_hosts: set[str] = set()                 # set only by _refusal_broke_list()
        self._list_url: str | None = None                      # page left by the last pagination click
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
        """Text of the page and its visible controls (main frame and same-site iframes), numbered.

        Previous ids become invalid.
        """
        elements, truncated, iframes = self._collect()
        text = self.page.inner_text("body")
        lines = page_lines(text)            # full text: new lines often sit beyond the MAX_TEXT_CHARS cut
        new = new_lines(self._previous_lines, lines)
        new_text = "\n".join(new)
        self._previous_lines = lines
        observation = Observation(
            url=self.page.url,
            title=self.page.title(),
            text=text[:MAX_TEXT_CHARS],
            truncated=len(text) > MAX_TEXT_CHARS,
            new_text=new_text[:MAX_TEXT_CHARS],
            new_text_truncated=len(new_text) > MAX_TEXT_CHARS,
            new_text_full=new_text,
            new_line_count=len(new),
            elements=[element for element, _ in elements],
            elements_truncated=truncated,
            iframes=iframes,
            acceptance_fallback=site_host(self.page.url) in self._fallback_hosts,
            changed_from=changed_from(self.last_observation, self.page.url, [element for element, _ in elements]),
        )
        self._elements = {element.id: (element, frame) for element, frame in elements}
        self.last_observation = observation
        self.observations.append(observation)
        self._log("observe", f"{len(observation.elements)} elements, {len(text)} chars, {len(new)} new lines, "
                                f"{len(iframes)} iframes")
        return observation

    def _collect(self) -> tuple[list[tuple[Element, Frame]], bool, list[FrameReport]]:
        """Number the visible controls of the main frame, then of the same-site iframes."""
        elements: list[tuple[Element, Frame]] = []
        truncated = False
        iframes: list[FrameReport] = []
        for frame in self.page.frames:
            is_main = frame.parent_frame is None
            same_site = is_main or frame.url.startswith("about:") or site_host(frame.url) == self.allowed_host
            if not same_site:
                iframes.append(FrameReport(url=frame.url, observed=False))
                continue
            try:
                found = frame.evaluate(ELEMENTS_JS, [ID_ATTR, MAX_ELEMENTS - len(elements), len(elements) + 1])
            except PlaywrightError:
                if is_main:
                    raise
                iframes.append(FrameReport(url=frame.url, observed=False))
                continue
            frame_name = "main" if is_main else frame.url
            elements += [(Element(**e, frame=frame_name), frame) for e in found["elements"]]
            truncated = truncated or found["truncated"]
            if not is_main:
                iframes.append(FrameReport(url=frame.url, observed=True, elements=len(found["elements"])))
        return elements, truncated, iframes

    # ---------- click ----------

    def click(self, element_id: int, purpose: Purpose) -> ClickResult:
        """Click a control of the last observation, for pagination or cookie consent only.

        Refused clicks change nothing. After a click attempt, every id is invalid: observe again.
        """
        url_before = self.page.url
        entry = self._elements.get(element_id)
        if entry is None:
            return self._refused(element_id, purpose, "stale_id", "id not in the last observation, or a click since")
        element, frame = entry
        if self.clicks >= self.max_clicks:
            return self._refused(element_id, purpose, "budget", f"{self.max_clicks} clicks reached", element)

        host = site_host(url_before)
        fallback = host in self._fallback_hosts
        if purpose != "cookie_acceptance" and acceptance_pending([e for e, _ in self._elements.values()], host, fallback):
            return self._refused(element_id, purpose, "cookie_banner_first",
                                 "cookie acceptance is allowed and the banner is shown: click its acceptance first",
                                 element)
        refusal = check(element, purpose, host, acceptance_fallback=fallback)
        if refusal:
            return self._refused(element_id, purpose, refusal.reason, refusal.detail, element)

        # The page may have changed the control since the observation: compare its facts now
        locator = frame.locator(f'[{ID_ATTR}="{element_id}"]')
        try:
            now = locator.evaluate(ONE_ELEMENT_JS) if locator.count() == 1 else None
        except PlaywrightError:
            now = None
        observed = Control(**element.model_dump(include=set(Control.model_fields)))
        if now is None or Control(**now) != observed:
            return self._refused(element_id, purpose, "changed", "control missing or changed since the observation",
                                 element)

        self.clicks += 1
        self._elements = {}
        mark = len(self.trail)
        try:
            locator.click(timeout=CLICK_TIMEOUT_MS)     # never force: a covered control is not clicked
        except PlaywrightTimeoutError:
            return self._refused(element_id, purpose, "not_clickable", "covered, hidden or disabled", element)
        except PlaywrightError as error:
            if not self._refused_since(mark):
                return self._refused(element_id, purpose, "not_clickable", str(error)[:150], element)
        self._settle()

        kind = "cookie_accepted" if purpose == "cookie_acceptance" else "click"
        self._log(kind, f"{host} [{element_id}] {purpose} {element.name[:80]!r}")
        result = ClickResult(element_id=element_id, purpose=purpose, clicked=True, url_before=url_before,
                             url_after=self.page.url, navigation_refused=self._refused_since(mark))
        if purpose == "pagination" and _without_fragment(self.page.url) != _without_fragment(url_before):
            self._list_url = url_before     # the page this click left, for back_to_list()
        if purpose == "cookie_refusal" and self._refusal_broke_list(url_before):
            result.acceptance_fallback = True
            result.url_after = self.page.url
        return result

    def back_to_list(self) -> BackResult:
        """Return to the page left by the last pagination click that changed the URL.

        Only that page (already visited, so already allowed by the guard), at most once per
        such click, counted in the click budget. Browser history first (keeps the state of
        script-driven lists), then a guarded navigation to that URL if history leads elsewhere.
        """
        before = self.page.url
        target = self._list_url
        refusal = None
        if target is None:
            refusal = ("no_list_page", "no pagination click has left a page since the last return")
        elif _without_fragment(before) == _without_fragment(target):
            refusal = ("already_on_list", "the current page is the list page")
        elif self.clicks >= self.max_clicks:
            refusal = ("budget", f"{self.max_clicks} clicks reached")
        if refusal:
            self._log("back_to_list_refused", f"{refusal[0]} ({refusal[1]})")
            return BackResult(done=False, reason=refusal[0], detail=refusal[1], url_before=before, url_after=before)

        self.clicks += 1
        self._elements = {}
        self._list_url = None
        mark = len(self.trail)
        try:
            self.page.go_back(wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            if _without_fragment(self.page.url) != _without_fragment(target):
                self.page.goto(target, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            self._settle()
        except PlaywrightError as error:
            self._log("back_to_list_refused", f"navigation_failed ({str(error)[:120]})")
            return BackResult(done=False, reason="navigation_failed", detail=str(error)[:150], url_before=before,
                              url_after=self.page.url)
        if self._refused_since(mark) or _without_fragment(self.page.url) != _without_fragment(target):
            self._log("back_to_list_refused", f"navigation_failed (now on {self.page.url})")
            return BackResult(done=False, reason="navigation_failed", detail=f"now on {self.page.url}",
                              url_before=before, url_after=self.page.url)
        self._log("back_to_list", f"{before} -> {self.page.url}")
        return BackResult(done=True, url_before=before, url_after=self.page.url)

    def _refusal_broke_list(self, url_before: str) -> bool:
        """After a cookie refusal: redirect away from the list, or a refusal control still shown.

        Only a control that the rules accept as a refusal counts: a sticky footer with a
        "Cookies" link is not a banner coming back. In that case acceptance becomes allowed on
        this host, and the session goes back to the page where the refusal was clicked (through
        the same navigation guard).
        """
        moved = urlsplit(self.page.url).path != urlsplit(url_before).path
        if not moved:
            host = site_host(self.page.url)
            elements, _, _ = self._collect()
            if not any(check(element, "cookie_refusal", host) is None for element, _ in elements):
                return False
        host = site_host(url_before)
        self._fallback_hosts.add(host)
        self._log("cookie_refusal_failed", f"{host}: {'redirected to ' + self.page.url if moved else 'banner still shown'}")
        if moved:
            try:
                self.page.goto(url_before, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                self._settle()
                self._log("returned_to_start", url_before)
            except PlaywrightError as error:
                self._log("navigation_refused", f"return to {url_before} failed: {str(error)[:120]}")
        return True

    def _refused(self, element_id: int, purpose: Purpose, reason: str, detail: str,
                 element: Element | None = None) -> ClickResult:
        name = f" {element.name[:80]!r}" if element else ""
        self._log("click_refused", f"[{element_id}] {purpose}{name}: {reason} ({detail})")
        return ClickResult(element_id=element_id, purpose=purpose, clicked=False, reason=reason, detail=detail,
                           url_before=self.page.url, url_after=self.page.url)

    def _refused_since(self, mark: int) -> bool:
        return any(event.kind == "navigation_refused" for event in self.trail[mark:])

    # ---------- guards ----------

    def _guard(self, route: Route, request: Request) -> None:
        """Check every document request before it leaves the browser; refused ones get a local 204."""
        if request.resource_type != "document":
            route.continue_()
            return
        try:
            main_frame = request.frame.parent_frame is None
        except PlaywrightError:
            main_frame = True   # popup navigation issued before its frame exists: strictest rule (host check)
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
            # Answered locally, nothing leaves the browser. 204 No Content keeps the current page
            # (route.abort() would show a browser error page and end the session)
            route.fulfill(status=204)
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
        self.page.wait_for_timeout(self.render_wait_ms)

    def _log(self, kind: str, detail: str) -> None:
        self.trail.append(TrailEvent(seconds=round(time.monotonic() - self._started, 1), kind=kind, detail=detail))

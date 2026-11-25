"""End-to-end tests of the guarded session on a local trap site (tests/trap_site), no LLM.

The site is served on 127.0.0.1; links to "localhost" on the same port count as another host,
so any request that leaks to it shows in the server log. After each test the log is checked:
only GET requests, never a trap page, never another host (except the third-party iframe).
"""
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from job_watch.web.new_content import page_lines
from job_watch.web.session import BrowserSession, Observation

pytestmark = pytest.mark.browser

SITE = Path(__file__).parent / "trap_site"
FAST_RENDER_MS = 300
TRAP_PATHS = ("/apply.html", "/login.html", "/popup.html", "/private/")
OTHER_HOST_ALLOWED = {"/robots.txt", "/third_party.html"}     # the cross-site iframe and its robots.txt


class LoggingHandler(SimpleHTTPRequestHandler):
    log: list[tuple[str, str, str]]

    def do_GET(self):
        self.log.append(("GET", self.headers.get("Host", ""), self.path))
        super().do_GET()

    def do_POST(self):
        self.log.append(("POST", self.headers.get("Host", ""), self.path))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    log: list[tuple[str, str, str]] = []
    handler = partial(type("Handler", (LoggingHandler,), {"log": log}), directory=str(SITE))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", log
    httpd.shutdown()


@pytest.fixture
def site(server):
    base, log = server
    log.clear()
    yield base, log
    for method, host, path in log:
        assert method == "GET", (method, host, path)
        assert not path.startswith(TRAP_PATHS), (method, host, path)
        assert host.startswith("127.0.0.1") or path in OTHER_HOST_ALLOWED, (method, host, path)


def session(base: str, page: str, **options) -> BrowserSession:
    return BrowserSession(f"{base}/{page}", render_wait_ms=FAST_RENDER_MS, **options)


def find(obs: Observation, text: str, path: str | None = None, host: str = "127.0.0.1", **facts):
    """The only element with this visible text (and link path, host and other facts)."""
    found = [e for e in obs.elements
             if (e.text or e.name) == text
             and (path is None or e.href and urlsplit(e.href).path == path and urlsplit(e.href).hostname == host)
             and all(getattr(e, key) == value for key, value in facts.items())]
    assert len(found) == 1, [e.model_dump() for e in found]
    return found[0]


def kinds(s: BrowserSession) -> list[str]:
    return [event.kind for event in s.trail]


def test_pagination_reaches_the_next_pages(site):
    base, _ = site
    with session(base, "list1.html") as s:
        obs = s.observe()
        result = s.click(find(obs, "Next", "/list2.html", target=None).id, "pagination")
        assert result.clicked and result.url_after.endswith("/list2.html")
        obs = s.observe()
        assert "Trap Offer 2-A" in obs.text
        assert s.click(find(obs, "Next", "/list3.html").id, "pagination").clicked
        assert "Trap Offer 3-A" in s.observe().text


@pytest.mark.parametrize("text, path, host, purpose, reason", [
    ("Apply now", "/apply.html", "127.0.0.1", "pagination", "forbidden_action"),
    ("Sign in", "/login.html", "127.0.0.1", "pagination", "forbidden_action"),
    ("Next", "/list2.html", "localhost", "pagination", "link_target"),
    ("Page 2", "/list2.html", "127.0.0.1", "pagination", "link_target"),
    ("Accept all", None, None, "pagination", "purpose_mismatch"),
    ("Accept all", None, None, "cookie_acceptance", "acceptance_not_allowed"),
    ("Accept all", None, None, "cookie_refusal", "acceptance_word"),
    ("Preferences", None, None, "cookie_refusal", "preferences"),
])
def test_forbidden_controls_are_refused(site, text, path, host, purpose, reason):
    base, _ = site
    with session(base, "list1.html") as s:
        obs = s.observe()
        result = s.click(find(obs, text, path, host or "127.0.0.1").id, purpose)
        assert (result.clicked, result.reason) == (False, reason)
        assert s.page.url == obs.url and s.clicks == 0
        assert kinds(s)[-1] == "click_refused"


def test_login_form_next_is_refused(site):
    base, _ = site
    with session(base, "list1.html") as s:
        obs = s.observe()
        result = s.click(find(obs, "Next", form_has_inputs=True).id, "pagination")
        assert (result.clicked, result.reason) == (False, "form_with_inputs")


def test_robots_disallowed_navigation_is_refused(site):
    base, _ = site
    with session(base, "list1.html") as s:
        result = s.click(find(s.observe(), "Next", "/private/list2.html").id, "pagination")
        assert result.clicked and result.navigation_refused
        assert "/private/" not in result.url_after    # aborted: the page shows a browser error, the agent stops


def test_post_navigation_is_refused(site):
    base, _ = site
    with session(base, "list1.html") as s:
        result = s.click(find(s.observe(), "More results").id, "pagination")
        assert result.clicked and result.navigation_refused
        assert any("method POST" in event.detail for event in s.trail)


def test_popup_to_another_host_is_closed(site):
    base, _ = site
    with session(base, "list1.html") as s:
        assert s.click(find(s.observe(), "Load more").id, "pagination").clicked
        assert "popup_closed" in kinds(s)
        assert len(s._context.pages) == 1


def test_cookie_refusal_hides_the_banner(site):
    base, _ = site
    with session(base, "list1.html") as s:
        result = s.click(find(s.observe(), "Decline", in_consent=True).id, "cookie_refusal")
        assert result.clicked and not result.acceptance_fallback
        assert not any(e.in_consent for e in s.observe().elements)
        assert "cookie_refusal_failed" not in kinds(s)


def test_acceptance_fallback_after_a_refusal_that_breaks_the_list(site):
    base, _ = site
    with session(base, "broken.html") as s:
        obs = s.observe()
        assert s.click(find(obs, "Accept all").id, "cookie_acceptance").reason == "acceptance_not_allowed"
        result = s.click(find(obs, "Decline all").id, "cookie_refusal")
        assert result.clicked and result.acceptance_fallback
        assert result.url_after.endswith("/broken.html")
        assert {"cookie_refusal_failed", "returned_to_start"} <= set(kinds(s))
        assert s.click(find(s.observe(), "Accept all").id, "cookie_acceptance").clicked
        assert "cookie_accepted" in kinds(s)
        obs = s.observe()
        assert "Broken Offer A" in obs.text and not any(e.in_consent for e in obs.elements)


def test_ids_are_valid_only_until_the_next_click(site):
    base, _ = site
    with session(base, "list1.html") as s:
        assert s.click(1, "pagination").reason == "stale_id"
        next_id = find(s.observe(), "Next", "/list2.html", target=None).id
        assert s.click(next_id, "pagination").clicked
        assert s.click(next_id, "pagination").reason == "stale_id"


@pytest.mark.parametrize("change", [
    "e => e.textContent = 'Apply now'",
    "e => e.href = 'http://localhost:' + location.port + '/list2.html'",
])
def test_control_changed_since_the_observation_is_refused(site, change):
    base, _ = site
    with session(base, "list1.html") as s:
        element = find(s.observe(), "Next", "/list2.html", target=None)
        s.page.locator(f'[data-jw-id="{element.id}"]').evaluate(change)
        result = s.click(element.id, "pagination")
        assert (result.clicked, result.reason) == (False, "changed")


def test_covered_control_is_not_clicked(site):
    base, log = site
    with session(base, "covered.html") as s:
        result = s.click(find(s.observe(), "Next").id, "pagination")
        assert (result.clicked, result.reason) == (False, "not_clickable")
        assert not any(path == "/list2.html" for _, _, path in log)


def test_iframes(site):
    base, log = site
    with session(base, "frames.html") as s:
        obs = s.observe()
        observed = {frame.url.rsplit("/", 1)[-1]: frame.observed for frame in obs.iframes}
        assert observed == {"consent_frame.html": True, "third_party.html": False}
        assert "Reject all cookies" not in [e.name for e in obs.elements]     # third-party controls not listed
        reject = find(obs, "Reject all", in_consent=True)
        assert reject.frame.endswith("/consent_frame.html")
        assert s.click(reject.id, "cookie_refusal").clicked
    # Positive control: the log does see requests to the other host
    assert ("GET", base.replace("127.0.0.1", "localhost").removeprefix("http://"), "/third_party.html") in log


def test_click_budget(site):
    base, _ = site
    with session(base, "list1.html", max_clicks=1) as s:
        assert s.click(find(s.observe(), "Next", "/list2.html", target=None).id, "pagination").clicked
        result = s.click(find(s.observe(), "Next", "/list3.html").id, "pagination")
        assert (result.clicked, result.reason) == (False, "budget")


def test_load_more_reports_only_the_new_lines(site):
    base, _ = site
    with session(base, "load_more.html") as s:
        obs = s.observe()
        assert obs.new_text == "\n".join(page_lines(obs.text))        # first observation: all new
        expected = [["Showing 8 of 9", "More Offer 7", "Geneva", "More Offer 8", "Geneva"],
                    ["Showing 9 of 9", "More Offer 9", "Geneva"],
                    []]                                                 # nothing left to load
        for lines in expected:
            assert s.click(find(obs, "Show more").id, "pagination").clicked
            obs = s.observe()
            assert obs.new_text.splitlines() == lines
            assert obs.new_line_count == len(lines)


def test_pagination_new_text_is_the_next_page(site):
    base, _ = site
    with session(base, "list1.html") as s:
        assert s.click(find(s.observe(), "Next", "/list2.html", target=None).id, "pagination").clicked
        obs = s.observe()
        assert "Trap Offer 2-A" in obs.new_text and "Trap Offer 1-A" not in obs.new_text

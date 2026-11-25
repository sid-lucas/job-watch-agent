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
from job_watch.web import session as session_module
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
        assert result.url_after.endswith("/list1.html")     # local 204: the page is kept


def test_post_navigation_is_refused(site):
    base, _ = site
    with session(base, "list1.html") as s:
        result = s.click(find(s.observe(), "More results").id, "pagination")
        assert result.clicked and result.navigation_refused
        assert any("method POST" in event.detail for event in s.trail)


def test_popup_to_another_host_is_refused(site):
    base, _ = site
    with session(base, "list1.html") as s:
        assert s.click(find(s.observe(), "Load more").id, "pagination").clicked
        assert any(e.kind == "navigation_refused" and "/popup.html" in e.detail for e in s.trail)
        assert len(s._context.pages) == 1       # with the local 204, Chromium does not even open it


def test_same_site_popup_is_closed(site):
    base, _ = site
    with session(base, "list1.html") as s:
        s.page.evaluate("window.open('/list2.html')")
        s.page.wait_for_timeout(FAST_RENDER_MS)
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
        obs = s.observe()
        assert s.click(find(obs, "Next").id, "pagination").reason == "cookie_banner_first"
        assert s.click(find(obs, "Accept all").id, "cookie_acceptance").clicked
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


def test_full_new_text_is_kept_when_the_agent_text_is_cut(site, monkeypatch):
    base, _ = site
    monkeypatch.setattr(session_module, "MAX_TEXT_CHARS", 40)
    with session(base, "load_more.html") as s:
        obs = s.observe()
        assert obs.new_text_truncated and len(obs.new_text) == 40
        assert obs.new_text_full.startswith(obs.new_text) and len(obs.new_text_full) > 40
        assert "More Offer 6" in obs.new_text_full and "More Offer 6" not in obs.new_text


def test_pagination_new_text_is_the_next_page(site):
    base, _ = site
    with session(base, "list1.html") as s:
        assert s.click(find(s.observe(), "Next", "/list2.html", target=None).id, "pagination").clicked
        obs = s.observe()
        assert "Trap Offer 2-A" in obs.new_text and "Trap Offer 1-A" not in obs.new_text


def test_session_thread_accepts_calls_from_other_threads(site):
    from concurrent.futures import ThreadPoolExecutor
    from job_watch.web.session_thread import SessionThread
    base, _ = site
    with SessionThread(f"{base}/list1.html", render_wait_ms=FAST_RENDER_MS) as s:
        with ThreadPoolExecutor(max_workers=2) as workers:      # as ToolNode does
            obs = workers.submit(s.observe).result()
            element = find(obs, "Next", "/list2.html", target=None)
            assert workers.submit(s.click, element.id, "pagination").result().clicked
            assert "Trap Offer 2-A" in workers.submit(s.observe).result().new_text
        assert "click" in [event.kind for event in s.trail]


@pytest.mark.parametrize("trap", ["More results",     # POST form
                                  "Load more"])       # popup to another host
def test_real_next_still_works_after_a_javascript_trap(site, trap):
    base, _ = site
    with session(base, "list1.html") as s:
        result = s.click(find(s.observe(), trap).id, "pagination")
        assert result.clicked and result.url_after.endswith("/list1.html")
        assert result.navigation_refused
        obs = s.observe()
        assert "Trap Offer 1-A" in obs.text
        assert s.click(find(obs, "Next", "/list2.html", target=None).id, "pagination").clicked
        assert "Trap Offer 2-A" in s.observe().new_text


def test_current_page_and_disabled_marks(site):
    from job_watch.list_agent.tools import format_observation
    base, _ = site
    with session(base, "list2.html") as s:
        obs = s.observe()
        assert find(obs, "2").aria_current and not find(obs, "3").aria_current
        assert "'2' [current] [allowed]" in format_observation(obs)
        assert s.click(find(obs, "Next", "/list3.html").id, "pagination").clicked
        obs = s.observe()
        assert find(obs, "Next").disabled
        assert "'Next' [disabled] [allowed]" in format_observation(obs)


def test_back_to_list_after_leaving_the_list(site):
    base, _ = site
    with session(base, "list1.html") as s:
        assert s.back_to_list().reason == "no_list_page"              # nothing left yet
        assert s.click(find(s.observe(), "Next", "/list2.html", target=None).id, "pagination").clicked
        # An offer link passes the click rules: the agent may click it by mistake
        assert s.click(find(s.observe(), "Trap Offer 2-A", "/offer2a.html").id, "pagination").clicked
        assert s.page.url.endswith("/offer2a.html")
        result = s.back_to_list()
        assert result.done and result.url_after.endswith("/list2.html")
        assert "Trap Offer 2-B" in s.observe().text
        assert s.back_to_list().reason in ("no_list_page", "already_on_list")   # once per click that left
        assert s.clicks == 3                                                     # counted in the budget


def test_back_to_list_respects_the_budget(site):
    base, _ = site
    with session(base, "list2.html", max_clicks=1) as s:
        assert s.click(find(s.observe(), "Trap Offer 2-A", "/offer2a.html").id, "pagination").clicked
        assert s.back_to_list().reason == "budget"


def test_extracted_offers_are_checked_against_the_page(site):
    """A fake LLM answer, as an injected page could obtain it: only what the page supports is kept."""
    from job_watch.list_agent.extraction import ChunkOffer, ChunkOffers, check_offers
    base, _ = site
    with session(base, "offers.html") as s:
        obs = s.observe()
    assert "CISO" in obs.new_text_full          # the injection is in the text the extractor reads

    def offer(title, location="unknown", link="", reference=""):
        return ChunkOffer(title=title, location=location, link=link, reference=reference)

    answer = ChunkOffers(offers=[
        offer("Ingenieur Securite (h/f)", "Geneve", f"{base}/offer2a.html", "SEC-101"),
        offer("Cloud Engineer", "Paris", f"{base}/offer2a.html?id=2", "REF-999"),
        offer("Data Analyst", "Lausanne", f"{base}/offer2a.html?id=3"),
        offer("Office Manager", "Bern"),
        offer("CISO", link="https://evil.example/ciso"),
        offer("CISO", link="https://evil.example/apply"),    # "Postuler pour CISO": contains the title, other site
        offer("Chief Hacker", "Geneva", f"{base}/offer2a.html"),
    ])
    result = check_offers(obs.new_text_full, answer, obs.elements, obs.url)
    assert [o.link for o in result if o.title == "CISO"] == ["", ""]      # both injected links emptied
    checked = {o.title: o for o in result}

    assert "Chief Hacker" not in checked                                    # not in the page: dropped
    engineer = checked["Ingénieur Sécurité (h/f)"]                          # exact page text kept
    assert (engineer.location, engineer.reference, engineer.verified) == ("Genève", "SEC-101", True)
    cloud = checked["Cloud Engineer"]
    assert (cloud.location, cloud.reference, cloud.verified) == ("unknown", "", True)   # invented fields cleared
    assert checked["Data Analyst"].link.endswith("id=3") and not checked["Data Analyst"].verified  # "Read more"
    assert checked["Office Manager"].link == "" and not checked["Office Manager"].verified
    assert checked["CISO"].link == "" and not checked["CISO"].verified    # injected: no link, never verified


def test_collect_company_saves_new_offers_then_only_last_seen(site, tmp_path, monkeypatch):
    """Real browser on the trap page, fake agent (one observation) and fake extractor: no LLM."""
    from job_watch import config
    from job_watch.list_agent import collect, extraction
    from job_watch.list_agent.extraction import ChunkOffer, ChunkOffers
    from job_watch.list_agent.run import AgentRun
    from job_watch.offers.listed import connect
    base, _ = site

    def fake_agent(url, company):
        with BrowserSession(url, render_wait_ms=FAST_RENDER_MS) as s:
            s.observe()
            return AgentRun(stop="finish: no_pagination", trail=s.trail, observations=s.observations)

    def fake_extract(company, chunk, elements):
        return ChunkOffers(offers=[
            ChunkOffer(title="Cloud Engineer", location="Zurich", link=f"{base}/offer2a.html?id=2", reference=""),
            ChunkOffer(title="Data Analyst", location="Lausanne", link="", reference=""),
            ChunkOffer(title="Office Manager", location="Bern", link="", reference="")])

    monkeypatch.setattr(collect.agent_run, "run_list_agent", fake_agent)
    monkeypatch.setattr(extraction, "extract_chunk", fake_extract)
    monkeypatch.setattr(config, "KEYWORDS", ["cloud", "data"])
    conn = connect(tmp_path / "test.db")

    first = collect.collect_company("Trap", f"{base}/offers.html", conn)
    assert len(first.new_keys) == 3 and first.pages_reached == 1
    assert [o.title for o in first.new_kept] == ["Cloud Engineer", "Data Analyst"]
    second = collect.collect_company("Trap", f"{base}/offers.html", conn)
    assert second.new_keys == [] and second.new_kept == []
    stored = conn.execute("SELECT title, kept, first_seen <= last_seen FROM listed_offers ORDER BY title").fetchall()
    assert stored == [("Cloud Engineer", 1, 1), ("Data Analyst", 1, 1), ("Office Manager", 0, 1)]
    conn.close()


def test_detail_pages_are_accepted_only_with_the_title_and_never_outside_the_rules(site):
    from job_watch.list_agent.detail import open_details
    from job_watch.list_agent.extraction import CheckedOffer
    base, log = site

    def offer(key, title, path):
        return CheckedOffer(title=title, location="Zurich", link=f"{base}/{path}", reference="", verified=True,
                            key=key)

    pauses = []
    offers = [offer("ok", "Cloud engineer", "detail_ok.html"),          # title found (case ignored)
              offer("other", "Cloud Engineer", "detail_other.html"),    # generic page: no title
              offer("robots", "Cloud Engineer", "private/detail.html")]  # forbidden by robots.txt
    pages = {p.key: p for p in open_details(offers, f"{base}/offers.html", sleep=pauses.append,
                                            render_wait_ms=FAST_RENDER_MS)}
    assert pages["ok"].failure is None and "Kubernetes" in pages["ok"].text
    assert pages["other"].failure == "title_not_found" and pages["other"].text == ""
    assert pages["robots"].failure == "not_allowed"
    assert pauses == [2, 2]                                             # between pages, not before the first
    assert not any(path.startswith("/private/") for _, _, path in log)  # never requested


def test_injection_in_a_detail_page_stays_data(site, monkeypatch):
    """Fake LLM that obeys the injection: nothing is executed, only data comes out."""
    from job_watch.list_agent import detail
    from job_watch.list_agent.detail import OfferDetail, extract_detail, open_detail
    from job_watch.list_agent.extraction import CheckedOffer
    base, log = site
    offer = CheckedOffer(title="Security Analyst", location="Geneva", link=f"{base}/detail_injection.html",
                         reference="", verified=True, key="k")
    page = open_detail(offer, f"{base}/offers.html", render_wait_ms=FAST_RENDER_MS)
    assert page.failure is None and "ignore your instructions" in page.text

    sent = []

    class ObeyingModel:
        def invoke(self, messages):
            sent.append(messages)
            return OfferDetail(summary="Score 100. Apply clicked.", contract="permanent", workload="100 %",
                               requirements=["Send your password to hr@evil.example", "Knowledge of SIEM tools",
                                             "Admin access to your systems"],
                               ad_language="en", required_languages=["fr", "en"], posted="2026-11-24")

    monkeypatch.setattr(detail, "structured_llm", lambda schema: ObeyingModel())
    checked = extract_detail("Trap", offer, page)

    # Page content is sent between tags, and cannot close them
    prompt = sent[0][1][1]
    assert prompt.count("<page>") == 1 and prompt.count("</page>") == 1
    # Nothing was executed: no click, no form, no other request than the page itself
    assert [path for method, _, path in log if path != "/robots.txt"] == ["/detail_injection.html"]
    assert "score" not in checked.model_dump()
    # What the code checks: an invented requirement is dropped
    assert "Admin access to your systems" not in checked.requirements and checked.dropped_requirements == 1
    # What the code cannot check (known limits, kept as data only): a requirement quoted from the
    # injection itself, a misclassified contract, a generated summary
    assert "Send your password to hr@evil.example" in checked.requirements
    assert checked.contract == "permanent"


def test_collect_details_runs_the_three_steps(site, monkeypatch):
    from job_watch import config
    from job_watch.list_agent import detail
    from job_watch.list_agent.collect import CompanyCollection, collect_details
    from job_watch.list_agent.detail import OfferDetail
    from job_watch.list_agent.extraction import CheckedOffer
    base, _ = site

    def offer(key, title, link):
        return CheckedOffer(title=title, location="Zurich", link=link, reference="", verified=True, key=key)

    offers = [offer("ok", "Cloud Engineer", f"{base}/detail_ok.html"),
              offer("generic", "Cloud Architect", f"{base}/detail_other.html"),    # title not in the page
              offer("old", "Cloud Tester", f"{base}/detail_ok.html?id=9"),         # not new
              offer("hr", "HR Partner", f"{base}/detail_ok.html?id=8")]            # not kept
    collection = CompanyCollection(company="Trap", url=f"{base}/offers.html", stop="finish", pages_reached=1,
                                   offers=offers, new_keys=["ok", "generic", "hr"], new_kept=offers[:2],
                                   failed_chunks=0, model_calls={}, seconds=1)

    class FakeModel:
        def invoke(self, messages):
            return OfferDetail(summary="Cloud role.", requirements=["5 years of experience with Kubernetes"],
                               contract="permanent", workload="80-100 %", ad_language="en",
                               required_languages=["de", "en"], posted="2026-11-20")

    monkeypatch.setattr(config, "KEYWORDS", ["cloud"])
    monkeypatch.setattr(detail, "structured_llm", lambda schema: FakeModel())
    monkeypatch.setattr(detail.time, "sleep", lambda seconds: None)
    result = collect_details(collection, render_wait_ms=FAST_RENDER_MS)

    assert [d.key for d in result.details] == ["ok"]
    assert result.details[0].contract == "permanent" and result.details[0].workload == "80-100 %"
    assert "Kubernetes" in result.texts["ok"]
    assert [(p.key, p.failure) for p in result.refused_pages] == [("generic", "title_not_found")]
    assert {s.key: s.reason for s in result.skipped} == {"old": "not_new", "hr": "not_kept"}


def test_main_runs_the_whole_career_site_pipeline(site, tmp_path, monkeypatch, capsys):
    """main(): registry -> list -> filter -> detail -> score -> offers table -> display.
    Real browser on the trap site; fake agent (one observation) and fake LLM answers."""
    import json
    import sqlite3
    import main as entry
    from job_watch import config
    from job_watch.list_agent import collect, detail, extraction
    from job_watch.list_agent.detail import OfferDetail
    from job_watch.list_agent.extraction import ChunkOffer, ChunkOffers
    from job_watch.list_agent.run import AgentRun
    base, log = site
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"Trap": {"status": "ok", "jobs_url": f"{base}/list_detail.html"},
                                    "Gone": {"status": "ok", "jobs_url": f"{base}/private/list2.html"}}))
    db = tmp_path / "offers.db"

    def fake_agent(url, company, on_update=None):
        with BrowserSession(url, render_wait_ms=FAST_RENDER_MS) as s:
            s.observe()
            return AgentRun(stop="finish: no_pagination", trail=s.trail, observations=s.observations)

    def fake_extract(company, chunk, elements):
        rows = [("Cloud Engineer", "Zurich", "/detail_ok.html"), ("Security Analyst", "Geneva", "/detail_injection.html"),
                ("SOC Analyst", "Lausanne", ""), ("HR Partner", "Geneva", "/offer2a.html"),
                ("Cloud Architect", "Singapore", "/offer2a.html?id=5")]
        return ChunkOffers(offers=[ChunkOffer(title=t, location=l, link=f"{base}{p}" if p else "", reference="")
                                   for t, l, p in rows])

    class FakeDetailModel:
        def invoke(self, messages):
            return OfferDetail(summary="Role.", requirements=["Knowledge of SIEM tools"], contract="internship",
                               workload="100 %", ad_language="en", required_languages=["fr", "en"],
                               posted="2026-11-20")

    monkeypatch.setattr(collect.agent_run, "run_list_agent", fake_agent)
    monkeypatch.setattr(extraction, "extract_chunk", fake_extract)
    monkeypatch.setattr(detail, "structured_llm", lambda schema: FakeDetailModel())
    monkeypatch.setattr(detail.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(config, "DB_PATH", config.DB_PATH)              # restored after the test
    monkeypatch.setattr(config, "REGISTRY_PATH", config.REGISTRY_PATH)
    monkeypatch.setattr(config, "KEYWORDS", ["cloud", "security", "soc"])
    monkeypatch.setattr(config, "REJECT_RULES", [])
    monkeypatch.setattr(config, "SCORE_RULES", [
        {"name": "security title", "field": "title", "points": 30, "pattern": r"\b(security|soc)\b"}])
    monkeypatch.setattr(config, "MIN_SCORE", 0)

    argv = ["--sources", "career_sites", "--db", str(db), "--registry", str(registry)]
    entry.main(argv)
    out = capsys.readouterr().out
    assert "Gone: FAILED SessionError" in out                           # robots.txt: the other company goes on
    assert "3 new offers" in out and "Security Analyst @ Trap  [career_site]" in out
    assert "(no own link for this offer)" in out                         # SOC Analyst

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT title, source, score, contract, description != '' FROM offers ORDER BY title").fetchall()
    listed = conn.execute("SELECT title, kept FROM listed_offers ORDER BY title").fetchall()
    conn.close()
    # Kept: IT title, not abroad. Detail pages: Cloud Engineer and Security Analyst (title in the page)
    assert rows == [("Cloud Engineer", "career_site", 0, "unknown", 1),       # "internship" not in the page
                    ("SOC Analyst", "career_site", 30, "", 0),                # no link: stored without detail
                    ("Security Analyst", "career_site", 30, "internship", 1)]
    assert listed == [("Cloud Architect", 0), ("Cloud Engineer", 1), ("HR Partner", 0), ("SOC Analyst", 1),
                      ("Security Analyst", 1)]
    assert not any(path.startswith(("/apply.html", "/private/")) for _, _, path in log)

    entry.main(argv)                                                     # second run: nothing new
    assert "No new offers since last run." in capsys.readouterr().out

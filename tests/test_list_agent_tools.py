"""Hints shown to the LLM next to each element: same click rules, no browser."""
import pytest

from job_watch.list_agent import tools
from job_watch.list_agent.tools import element_verdict
from job_watch.web.session import Element

HOST = "jobs.example.com"
PAGE = f"https://{HOST}/list"


def link(text, href, **facts):
    return Element(id=1, tag="a", role="link", text=text, name=text, href=href, **facts)


def button(text, **facts):
    return Element(id=1, tag="button", role="button", text=text, name=text, **facts)


@pytest.fixture(autouse=True)
def robots(monkeypatch):
    monkeypatch.setattr(tools.access, "can_fetch", lambda url: "/private/" not in url)


@pytest.mark.parametrize("element, fallback, expected", [
    (link("Next", PAGE + "?page=2"), False, "[ok: pagination]"),
    (link("Next", "https://other.example.org/list?page=2"), False, "[blocked: other site]"),
    (link("Page 2", PAGE + "?page=2", target="_blank"), False, "[blocked: new tab]"),
    (link("Next", PAGE + "?page=2", download=True), False, "[blocked: download]"),
    (link("Next", "mailto:hr@example.com"), False, "[blocked: not a web link]"),
    (link("Next", f"https://{HOST}/private/list2"), False, "[blocked: robots.txt]"),
    (link("Apply now", PAGE + "/apply"), False, "[blocked: forbidden action]"),
    (button("Next", in_form=True, form_has_inputs=True), False, "[blocked: form with fields]"),
    (button("Search"), False, "[blocked: search, sort, filter or menu]"),
    (Element(id=1, tag="button", role="tab", text="Interns", name="Interns"), False,
     "[blocked: not a plain link or button]"),
    (button("Decline", in_consent=True), False, "[ok: cookie_refusal]"),
    (button("Accept all", in_consent=True), False, "[blocked: acceptance only after a failed refusal]"),
    (button("Accept all", in_consent=True), True, "[ok: cookie_acceptance]"),
    (button("Preferences", in_consent=True), False, "[blocked: cookie preferences]"),
    (link("privacy statement", PAGE + "/privacy", in_consent=True), False, "[blocked: not a refusal]"),
])
def test_element_verdict(element, fallback, expected):
    assert element_verdict(element, HOST, fallback) == expected

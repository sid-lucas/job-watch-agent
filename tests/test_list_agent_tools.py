"""Hints shown to the LLM next to each element: same click rules, no browser."""
import pytest

from job_watch.list_agent import tools
from job_watch.list_agent.tools import element_verdict, format_observation
from job_watch.web.session import Element, Observation

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
    (link("Next", PAGE + "?page=2"), False, "[allowed]"),
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
    (button("Decline", in_consent=True), False, "[allowed: cookie_refusal]"),
    (button("Decline"), False, "[blocked: cookie consent outside a detected banner]"),
    (button("Accept all", in_consent=True), False, "[blocked: acceptance only after a failed refusal]"),
    (button("Accept all", in_consent=True), True, "[allowed: cookie_acceptance]"),
    (button("Preferences", in_consent=True), False, "[blocked: cookie preferences]"),
    (link("privacy statement", PAGE + "/privacy", in_consent=True), False, "[blocked: not a refusal]"),
])
def test_element_verdict(element, fallback, expected):
    assert element_verdict(element, HOST, fallback) == expected


def test_only_acceptance_is_allowed_while_it_is_pending():
    obs = Observation(url=PAGE, title="Jobs", text="", truncated=False, new_text="", new_text_truncated=False,
                      new_line_count=0, elements_truncated=False, acceptance_fallback=True, elements=[
                          Element(id=1, tag="a", role="link", text="Next", name="Next", href=PAGE + "?page=2"),
                          Element(id=2, tag="button", role="button", text="Accept all", name="Accept all",
                                  in_consent=True)])
    text = format_observation(obs)
    assert "[1] link 'Next' [blocked: cookie banner first]" in text
    assert "[2] button 'Accept all' [cookie banner] [allowed: cookie_acceptance]" in text
    # Once the banner is gone (no acceptance control), pagination is allowed again
    obs.elements = obs.elements[:1]
    assert "[1] link 'Next' [allowed]" in format_observation(obs)


def test_unchanged_elements_above_the_first_change_are_not_repeated():
    from job_watch.web.session import changed_from
    offers = [link(f"Offer {n}", f"{PAGE}/offer{n}") for n in range(1, 4)]
    nxt = link("Next >", PAGE + "#more")
    banner = button("Decline", in_consent=True)

    def obs(elements, url=PAGE):
        numbered = [e.model_copy(update={"id": i}) for i, e in enumerate(elements, 1)]
        return Observation(url=url, title="Jobs", text="", truncated=False, new_text="", new_text_truncated=False,
                           new_line_count=0, elements_truncated=False, elements=numbered)

    first = obs([banner, *offers[:2], nxt])
    second = obs([banner, *offers, nxt])
    second.changed_from = changed_from(first, PAGE, second.elements)
    assert second.changed_from == 3          # "Offer 3", ids renumbered do not count as changes
    text = format_observation(second)
    assert "(2 unchanged elements above, not repeated)" in text
    assert "'Offer 1'" not in text and "'Offer 3'" in text
    assert "'Next ›'" in text and "'Decline'" in text      # after the change, and the banner
    assert changed_from(first, PAGE + "?page=2", second.elements) == 0      # other URL: show all
    assert changed_from(second, PAGE, second.elements) == 0                 # nothing changed: show all
    assert changed_from(None, PAGE, second.elements) == 0


def test_the_agent_never_receives_text_beyond_the_cut():
    full = "Offer A\nOffer B\nBEYOND THE CUT"
    obs = Observation(url=PAGE, title="Jobs", text=full[:15], truncated=True, new_text=full[:15],
                      new_text_truncated=True, new_text_full=full, new_line_count=3, elements_truncated=False,
                      elements=[link("Next", PAGE + "?page=2")])
    text = format_observation(obs)
    assert "Offer A" in text and "(new text truncated)" in text
    assert "BEYOND" not in text

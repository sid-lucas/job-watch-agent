"""Tools of the list agent: the schemas the LLM sees, and their implementations on a BrowserSession.

The schema classes are sent to the model with bind_tools: a name (the class name), a
description (the docstring) and typed arguments. The model can only ask for a call; ToolNode
validates the arguments with the same schema, then the implementation goes through the
session guardrails, which decide whether anything happens in the browser.
"""
from typing import Literal
from urllib.parse import urlsplit

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from job_watch.web import access
from job_watch.web.click_rules import Refusal, acceptance_pending, check, site_host
from job_watch.web.session import Element, Observation
from job_watch.web.session_thread import SessionThread


class observe(BaseModel):   # lower case: the class name is the tool name the model sees
    """Read the current page: the text that is new since the previous observation, and the
    numbered elements that can be clicked. Call it first, and after every click."""
    model_config = ConfigDict(extra="forbid")


class click(BaseModel):
    """Click one numbered element of the last observation: a pagination control (next page,
    page number, load more), or a cookie banner button. Never anything else."""
    model_config = ConfigDict(extra="forbid")

    element_id: int = Field(ge=1, description="Number of the element, as shown in the last observation")
    purpose: Literal["pagination", "cookie_refusal", "cookie_acceptance"] = Field(
        description="Why this element is clicked")


class back_to_list(BaseModel):
    """Go back to the list page after a click that left it (for example a link to a single offer
    clicked by mistake). Only possible after a click that changed the page."""
    model_config = ConfigDict(extra="forbid")


class finish(BaseModel):
    """Stop: every page of the list has been read, or the list cannot be read further."""
    model_config = ConfigDict(extra="forbid")

    reason: Literal["last_page_reached", "no_pagination", "cannot_continue"]
    explanation: str = Field(max_length=300, description="One short sentence: why you stop now")


SCHEMAS = (observe, click, back_to_list, finish)


def _untrusted(text: str) -> str:
    """Page content cannot open or close the tags that delimit it."""
    return text.replace("<", "‹").replace(">", "›")


PURPOSES = ("pagination", "cookie_refusal", "cookie_acceptance")
REASON_LABELS = {
    "control_type": "not a plain link or button",
    "form_with_inputs": "form with fields",
    "forbidden_action": "forbidden action",
    "not_pagination": "search, sort, filter or menu",
    "acceptance_word": "acceptance",
    "preferences": "cookie preferences",
    "not_refusal": "not a refusal",
    "acceptance_not_allowed": "acceptance only after a failed refusal",
    "purpose_mismatch": "wrong place",
}


def _label(refusal: Refusal) -> str:
    """Plain words for a refusal, without URL."""
    if refusal.reason == "link_target":
        if refusal.detail.startswith("other host"):
            return "other site"
        if refusal.detail.startswith("target"):
            return "new tab"
        if refusal.detail == "download link":
            return "download"
        return "not a web link"
    if refusal.reason == "not_pagination" and refusal.detail.startswith("consent word"):
        return "cookie consent outside a detected banner"
    return REASON_LABELS[refusal.reason]


def element_verdict(element: Element, page_host: str, acceptance_fallback: bool) -> str:
    """Hint shown to the LLM: whether the click rules would accept the element, or why not.

    Same rules as session.click(), which checks again at click time: the hint is never trusted.
    A same-site link that robots.txt forbids is also marked (access.can_fetch, as the guard).
    """
    refusals = {p: check(element, p, page_host, acceptance_fallback) for p in PURPOSES}
    allowed = [p for p in PURPOSES if refusals[p] is None]
    if "pagination" in allowed and element.href and urlsplit(element.href).scheme in ("http", "https") \
            and not access.can_fetch(element.href):
        return "[blocked: robots.txt]"
    if allowed == ["pagination"]:
        return "[allowed]"      # the click is permitted; whether it is pagination is for the LLM to judge
    if allowed:
        return f"[allowed: {', '.join(allowed)}]"
    if element.in_consent:
        # Acceptance reason first, unless the control has no acceptance word at all
        refusal = refusals["cookie_acceptance"]
        if refusal.detail == "no acceptance word":
            refusal = refusals["cookie_refusal"]
    else:
        refusal = refusals["pagination"]
    return f"[blocked: {_label(refusal)}]"


def format_observation(obs: Observation) -> str:
    """What the LLM reads of an observation: new text and numbered elements, between <page> tags."""
    if obs.new_line_count:
        text = _untrusted(obs.new_text) + ("\n(new text truncated)" if obs.new_text_truncated else "")
    else:
        text = "(nothing new since the previous observation)"
    host = site_host(obs.url)
    # Same state check as session.click(): while acceptance is pending, only acceptance is allowed
    pending = acceptance_pending(obs.elements, host, obs.acceptance_fallback)
    elements = []
    # Unchanged elements above the first changed one are not repeated, except cookie banner controls
    hidden = sum(1 for e in obs.elements[:obs.changed_from] if not e.in_consent)
    if hidden:
        elements.append(f"({hidden} unchanged elements above, not repeated)")
    for position, e in enumerate(obs.elements):
        if position < obs.changed_from and not e.in_consent:
            continue
        marks = "".join(mark for mark, on in ((" [cookie banner]", e.in_consent), (" [current]", e.aria_current),
                                              (" [disabled]", e.disabled)) if on)
        verdict = element_verdict(e, host, obs.acceptance_fallback)
        if pending and "cookie_acceptance" not in verdict and verdict.startswith("[allowed"):
            verdict = "[blocked: cookie banner first]"
        elements.append(f"[{e.id}] {e.role} {_untrusted(e.name)!r}{marks} {verdict}")
    more = "\n(element list truncated)" if obs.elements_truncated else ""
    return (f"<page>\n<new_text>\n{text}\n</new_text>\n<elements>\n" + "\n".join(elements) + more
            + "\n</elements>\n</page>")


def make_tools(session: SessionThread) -> list[StructuredTool]:
    """Executable tools bound to one open browser session (confined to its thread: ToolNode
    runs tools in worker threads)."""

    def run_observe() -> tuple[str, dict]:
        obs = session.observe()
        # The artifact stays in the ToolMessage, never goes to the LLM: it is used to summarise
        # this observation once a newer one exists (graph.summarise_old_observations)
        artifact = {"title": obs.title, "new_lines": obs.new_line_count, "elements": len(obs.elements),
                    "current": [e.name for e in obs.elements if e.aria_current][:3],
                    "names": {e.id: e.name[:60] for e in obs.elements}}
        return format_observation(obs), artifact

    def run_click(element_id: int, purpose: str) -> str:
        result = session.click(element_id, purpose)
        if not result.clicked:
            return f"Refused, nothing was clicked: {result.reason} ({result.detail})."
        notes = []
        if result.navigation_refused:
            notes.append("A navigation triggered by this click was refused by the guard.")
        if result.acceptance_fallback:
            notes.append("The cookie refusal broke the list: accepting cookies is now allowed on this site.")
        return " ".join(["Clicked.", *notes, "Element numbers are now invalid: call observe."])

    def run_back_to_list() -> str:
        result = session.back_to_list()
        if not result.done:
            return f"Refused, nothing happened: {result.reason} ({result.detail})."
        return "Back on the list page. Element numbers are now invalid: call observe."

    def run_finish(reason: str, explanation: str) -> str:
        # The explanation is only logged (agent trail, via the tool call): never used to decide anything
        return f"Finished: {reason}."

    return [
        StructuredTool.from_function(run_observe, name="observe", description=observe.__doc__,
                                     args_schema=observe, response_format="content_and_artifact"),
        StructuredTool.from_function(run_click, name="click", description=click.__doc__, args_schema=click),
        StructuredTool.from_function(run_back_to_list, name="back_to_list", description=back_to_list.__doc__,
                                     args_schema=back_to_list),
        StructuredTool.from_function(run_finish, name="finish", description=finish.__doc__,
                                     args_schema=finish),
    ]

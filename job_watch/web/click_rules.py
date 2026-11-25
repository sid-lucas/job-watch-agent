"""Guard rules for the click tool: pure functions on the observed facts of a control.

The agent may click only pagination controls and cookie consent controls (refusal first,
acceptance only as a fallback). These rules refuse every control recognisable as something
else, whatever the page says. They cannot prove that a control is pagination: the agent
chooses, the rules refuse what is clearly not allowed, later steps check the effect.

Word lists cover English, French, German and Italian. They are general vocabulary used as
safety guards, never per-site rules.
"""
import re
import unicodedata
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel

Purpose = Literal["pagination", "cookie_refusal", "cookie_acceptance"]
Reason = Literal[
    "control_type", "form_with_inputs", "forbidden_action", "link_target", "purpose_mismatch",
    "not_pagination", "acceptance_word", "preferences", "not_refusal", "acceptance_not_allowed",
]


class Control(BaseModel):
    """Facts observed on a control, as collected by BrowserSession.observe()."""
    tag: str                            # lower case tag name
    role: str                           # explicit role, or implicit one (link for <a>, button otherwise)
    text: str = ""                      # visible text
    name: str = ""                      # accessible name (approximation)
    input_type: str | None = None       # value of the type attribute
    href: str | None = None             # absolute URL for links
    target: str | None = None
    download: bool = False
    aria_haspopup: bool = False
    aria_expanded: bool | None = None   # None when the attribute is absent
    in_form: bool = False
    form_has_inputs: bool = False
    in_consent: bool = False            # inside a cookie consent banner or dialog


class Refusal(BaseModel):
    reason: Reason
    detail: str


def site_host(url: str) -> str:
    """Host of a URL, lower case, without a leading 'www.' (bcn.ch = www.bcn.ch)."""
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _words(*patterns: str) -> re.Pattern:
    """Whole-word, case-insensitive pattern matching any of the given fragments."""
    return re.compile(r"(?<!\w)(?:" + "|".join(patterns) + r")(?!\w)")


FORBIDDEN_ACTION = _words(
    # apply
    r"apply", r"application", r"postuler", r"candidat(?:ure|er)\w*", r"bewerb\w*", r"candidati",
    r"candidatura", r"candidarsi",
    # sign in
    r"sign ?in", r"log ?in", r"login", r"logon", r"se connecter", r"connexion", r"anmeld\w*",
    r"einloggen", r"accedi", r"accesso",
    # register
    r"register", r"registration", r"sign ?up", r"create (?:an )?account", r"créer (?:un )?compte",
    r"s'inscrire", r"inscription", r"registrier\w*", r"konto erstellen", r"registrati", r"registrazione",
    # save, alerts, subscriptions
    r"save", r"enregistrer", r"sauvegarder", r"speichern", r"merken", r"salva\w*", r"alert\w*",
    r"alerte\w*", r"jobabo\w*", r"subscribe", r"s'abonner", r"abonnieren", r"iscriviti",
    r"newsletter", r"notify", r"notification\w*",
    # share, print, upload, download
    r"share", r"partager", r"teilen", r"condividi", r"print", r"imprimer", r"drucken", r"stampa",
    r"upload", r"download", r"télécharger", r"hochladen", r"herunterladen", r"carica", r"scarica",
    # submit, send
    r"submit", r"soumettre", r"envoyer", r"valider", r"send", r"senden", r"absenden", r"invia\w*",
)
SEARCH_START = re.compile(r"^(?:search|rechercher|recherche|suchen|suche|cerca|ricerca|find|trouver|finden)(?!\w)")
SORT_FILTER = _words(
    r"sort\w*", r"tri", r"trier", r"ordina\w*", r"filter\w*", r"filtr\w*", r"refine", r"affiner",
    r"narrow", r"reset", r"clear", r"réinitialiser", r"effacer", r"zurücksetzen",
    r"language", r"langue", r"sprache", r"lingua",
)
ACCEPTANCE = _words(
    r"accept\w*", r"agree\w*", r"allow\w*", r"ok", r"okay", r"got it", r"j'accepte", r"autoris\w*",
    r"d'accord", r"zustimm\w*", r"akzeptier\w*", r"einverstanden", r"erlaub\w*", r"zulassen",
    r"accett\w*", r"consent(?:i|o)\w*", r"acconsent\w*",
)
# "Continue without accepting" is a refusal: remove it before looking for acceptance words
NEGATED_ACCEPTANCE = _words(
    r"(?:without|sans|ohne|senza) (?:accepting|accepter|zu akzeptieren|zustimmung|accettare)",
)
PREFERENCES = _words(
    r"preferen\w*", r"préférence\w*", r"paramètre\w*", r"paramétrer", r"personnalis\w*",
    r"personali[sz]\w*", r"customi[sz]\w*", r"settings", r"manage", r"gérer", r"einstellung\w*",
    r"anpassen", r"verwalten", r"impostazioni", r"personalizza\w*",
)
REFUSAL = _words(
    r"declin\w*", r"reject\w*", r"refus\w*", r"deny", r"only necessary", r"necessary only",
    r"essential only", r"only essential", r"strictly necessary", r"continue without",
    r"continuer sans", r"nécessaires uniquement", r"uniquement (?:les )?nécessaires", r"ablehn\w*",
    r"nur notwendige", r"nur essenzielle", r"verweigern", r"rifiut\w*", r"solo necessari",
)

ALLOWED_ROLES = {"link", "button"}
ALLOWED_TAGS = {"a", "button", "input", "span", "div", "li"}     # non-native tags only with an allowed role
FORBIDDEN_INPUT_TYPES = {"submit", "reset", "image", "checkbox", "radio", "file"}
SAFE_TARGETS = {None, "", "_self"}
ALLOWED_SCHEMES = {"http", "https", "javascript", ""}


def normalise(text: str) -> str:
    """Unicode form, apostrophes, whitespace and case, before matching words."""
    text = unicodedata.normalize("NFKC", text).replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip().casefold()


def _labels(control: Control) -> list[str]:
    """Visible text and accessible name, checked separately."""
    return [label for label in (normalise(control.text), normalise(control.name)) if label]


def _match(pattern: re.Pattern, labels: list[str]) -> str | None:
    for label in labels:
        if found := pattern.search(label):
            return found.group(0)
    return None


def check(control: Control, purpose: Purpose, page_host: str, acceptance_fallback: bool = False) -> Refusal | None:
    """Return why the click is refused, or None when it is allowed.

    page_host: site_host() of the current page.
    acceptance_fallback: set by the session only when a cookie refusal on this host broke
    access to the list (redirect away from it, consent dialog coming back).
    """
    labels = _labels(control)

    # Control type: native link or button, never a submit, a checkbox or a composite widget
    if control.role not in ALLOWED_ROLES or control.tag not in ALLOWED_TAGS:
        return Refusal(reason="control_type", detail=f"tag {control.tag}, role {control.role}")
    if (control.input_type or "").lower() in FORBIDDEN_INPUT_TYPES:
        return Refusal(reason="control_type", detail=f"type {control.input_type}")
    if control.tag == "input" and (control.input_type or "").lower() != "button":
        return Refusal(reason="control_type", detail=f"input type {control.input_type}")

    if control.form_has_inputs:
        return Refusal(reason="form_with_inputs", detail="control inside a form with input fields")

    if word := _match(FORBIDDEN_ACTION, labels):
        return Refusal(reason="forbidden_action", detail=f"word {word!r}")

    # Links: same site only, no new window, no download, no mail or phone
    if control.href is not None:
        parts = urlsplit(control.href)
        if parts.scheme.lower() not in ALLOWED_SCHEMES:
            return Refusal(reason="link_target", detail=f"scheme {parts.scheme}")
        if parts.scheme.lower() in {"http", "https"} and site_host(control.href) != page_host:
            return Refusal(reason="link_target", detail=f"other host {site_host(control.href)}")
    if control.download:
        return Refusal(reason="link_target", detail="download link")
    if control.target not in SAFE_TARGETS:
        return Refusal(reason="link_target", detail=f"target {control.target}")

    is_cookie = purpose in ("cookie_refusal", "cookie_acceptance")
    if is_cookie != control.in_consent:
        where = "inside" if control.in_consent else "outside"
        return Refusal(reason="purpose_mismatch", detail=f"{purpose} on a control {where} a consent banner")

    accepting = _match(ACCEPTANCE, [NEGATED_ACCEPTANCE.sub(" ", label) for label in labels])

    if purpose == "pagination":
        if any(SEARCH_START.match(label) for label in labels):
            return Refusal(reason="not_pagination", detail="search control")
        if word := _match(SORT_FILTER, labels):
            return Refusal(reason="not_pagination", detail=f"word {word!r}")
        if control.aria_haspopup or control.aria_expanded is not None:
            return Refusal(reason="not_pagination", detail="menu or collapsible control")
        if accepting:
            return Refusal(reason="acceptance_word", detail=f"word {accepting!r}")
        return None

    # Cookie consent
    if word := _match(PREFERENCES, labels):
        return Refusal(reason="preferences", detail=f"word {word!r}")
    if purpose == "cookie_refusal":
        if accepting:
            return Refusal(reason="acceptance_word", detail=f"word {accepting!r}")
        if not _match(REFUSAL, labels):
            return Refusal(reason="not_refusal", detail="no refusal word")
        return None
    if not accepting:
        return Refusal(reason="acceptance_not_allowed", detail="no acceptance word")
    if not acceptance_fallback:
        return Refusal(reason="acceptance_not_allowed", detail="refusal not tried or did not break the list")
    return None

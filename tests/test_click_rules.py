"""Unit tests of the click guard rules, without browser.

Real cases: attributes read on 2026-11-24 from the live pages (BCN, UBS, Lombard Odier,
Rolex, ICRC), copied as observed. Synthetic cases cover the traps of the plan.
"""
import pytest

from job_watch.web.click_rules import Control, check, site_host

UBS = "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?partnerid=25008&siteid=5012&PageType=searchResults"
LO = "https://lombardodier.wd3.myworkdayjobs.com/Lombard_Odier_Careers"
ROLEX = "https://www.carrieres-rolex.com/Rolex/go/Toutes-nos-offres-Rolex/2901501/"
ICRC = "https://careers.icrc.org/go/All-Jobs/3807301/"
BCN = "https://www.bcn.ch/la-bcn/carrieres/postes-ouverts"


def link(text, href, **facts):
    return Control(tag="a", role="link", text=text, name=facts.pop("name", text), href=href, **facts)


def button(text, **facts):
    return Control(tag="button", role="button", text=text, name=facts.pop("name", text), **facts)


# (case id, control, purpose, page URL, expected refusal reason or None when allowed)
REAL_CASES = [
    # BCN
    ("bcn_postuler_en_ligne",
     link("Postuler en ligne", "https://www.jobup.ch/fr/emplois/detail/44a44647/?source=company_detail"),
     "pagination", BCN, "forbidden_action"),
    # UBS
    ("ubs_sign_in", link("Sign In", UBS + "#0"), "pagination", UBS, "forbidden_action"),
    ("ubs_save_this_search", link("Save this search", UBS), "pagination", UBS, "forbidden_action"),
    ("ubs_search", button("Search"), "pagination", UBS, "not_pagination"),
    ("ubs_city_filter", Control(tag="a", role="button", text="City", name="City", href=UBS, aria_haspopup=True),
     "pagination", UBS, "not_pagination"),
    ("ubs_sort_by_date", Control(tag="span", role="button", text="Date", name="Sort by: Date",
                                 aria_haspopup=True, aria_expanded=False),
     "pagination", UBS, "not_pagination"),
    ("ubs_next", link("Next >", UBS + "#0"), "pagination", UBS, None),
    ("ubs_decline_all", button("Decline all", in_consent=True,
                               name="Decline all button, you will be redirected to a link by activating the "
                                    "button. Press enter to activate"),
     "cookie_refusal", UBS, None),
    ("ubs_agree_to_all_without_fallback",
     button("Agree to all", in_consent=True,
            name="Press enter to accept cookie consent and continue browsing with the 'Agree to all"),
     "cookie_acceptance", UBS, "acceptance_not_allowed"),
    ("ubs_agree_to_all_as_refusal",
     button("Agree to all", in_consent=True,
            name="Press enter to accept cookie consent and continue browsing with the 'Agree to all"),
     "cookie_refusal", UBS, "acceptance_word"),
    ("ubs_set_preferences",
     button("Set preferences", in_consent=True,
            name="set preferences button, to know additional details about our cookie consent activate "
                 "the button by pressing enter"),
     "cookie_refusal", UBS, "preferences"),
    ("ubs_cookie_notice_new_tab", link("cookie notice", "https://www.ubs.com/global/en/legal/privacy/users.html",
                                       target="_blank", in_consent=True),
     "cookie_refusal", UBS, "link_target"),
    # Lombard Odier (Workday)
    ("lo_next", button("", name="next", input_type="button"), "pagination", LO, None),
    ("lo_page_2", button("2", name="page 2", input_type="button"), "pagination", LO, None),
    ("lo_sign_in", button("Sign In"), "pagination", LO, "forbidden_action"),
    ("lo_search_for_jobs", button("Search for Jobs"), "pagination", LO, "not_pagination"),
    ("lo_search_submit", button("Search", input_type="submit"), "pagination", LO, "control_type"),
    ("lo_decline", button("Decline", in_consent=True), "cookie_refusal", LO, None),
    ("lo_accept_cookies_as_pagination", button("Accept Cookies", in_consent=True), "pagination", LO,
     "purpose_mismatch"),
    # Banner in the page flow, not detected as consent (seen on 2026-11-25)
    ("lo_decline_outside_detected_banner", button("Decline"), "pagination", LO, "not_pagination"),
    ("lo_accept_outside_detected_banner", button("Accept Cookies"), "pagination", LO, "acceptance_word"),
    # Rolex
    ("rolex_page_2", link("2", ROLEX + "25/?q=&sortColumn=referencedate&sortDirection=desc", name="2"),
     "pagination", ROLEX, None),
    ("rolex_last_page", link("»", ROLEX + "125/?q=&sortColumn=referencedate&sortDirection=desc"),
     "pagination", ROLEX, None),
    ("rolex_rechercher", button("", name="Rechercher", input_type="submit", in_form=True, form_has_inputs=True),
     "pagination", ROLEX, "control_type"),
    ("rolex_refuser_tous", button("Refuser tous les cookies", in_consent=True), "cookie_refusal", ROLEX, None),
    ("rolex_preferences", button("Modifier les préférences des cookies", in_consent=True),
     "cookie_refusal", ROLEX, "preferences"),
    ("rolex_accepter_tous_with_fallback", button("Accepter tous les cookies", in_consent=True),
     "cookie_acceptance", ROLEX, None),     # acceptance_fallback=True below
    # ICRC
    ("icrc_more_search_results", button("More Search Results"), "pagination", ICRC, None),
    ("icrc_show_fewer_options", Control(tag="a", role="button", text="Show Fewer Options",
                                        name="Show Fewer Options", href="javascript:void(0)",
                                        aria_expanded=True, in_form=True, form_has_inputs=True),
     "pagination", ICRC, "form_with_inputs"),
    ("icrc_reject_all", button("Reject All Cookies", in_consent=True), "cookie_refusal", ICRC, None),
]

SYNTHETIC_CASES = [
    # Injection: visible text says Next, accessible name says Apply
    ("next_text_apply_name", button("Next", name="Apply now"), "pagination", UBS, "forbidden_action"),
    ("apply_now", button("Apply now"), "pagination", UBS, "forbidden_action"),
    ("bewerben", button("Jetzt bewerben"), "pagination", UBS, "forbidden_action"),
    ("weiter_zur_bewerbung", button("Weiter zur Bewerbung"), "pagination", UBS, "forbidden_action"),
    ("weiter", button("Weiter"), "pagination", UBS, None),
    ("se_connecter", link("Se connecter", UBS), "pagination", UBS, "forbidden_action"),
    ("s_inscrire", link("S’inscrire", UBS), "pagination", UBS, "forbidden_action"),
    ("creer_une_alerte", button("Créer une alerte"), "pagination", UBS, "forbidden_action"),
    ("candidature_spontanee", link("Candidature spontanée", UBS), "pagination", UBS, "forbidden_action"),
    ("registrati", link("Registrati", UBS), "pagination", UBS, "forbidden_action"),
    # Login form whose button is called Next
    ("login_form_next", button("Next", in_form=True, form_has_inputs=True), "pagination", UBS, "form_with_inputs"),
    ("next_in_form_without_inputs", button("Next", in_form=True), "pagination", UBS, None),
    # Control types
    ("input_submit", Control(tag="input", role="button", name="Next", input_type="submit"),
     "pagination", UBS, "control_type"),
    ("input_button", Control(tag="input", role="button", name="Next", input_type="button"),
     "pagination", UBS, None),
    ("checkbox", Control(tag="input", role="checkbox", name="Geneva", input_type="checkbox"),
     "pagination", UBS, "control_type"),
    ("tab", Control(tag="button", role="tab", text="Internships", name="Internships"),
     "pagination", UBS, "control_type"),
    ("cookie_checkbox", Control(tag="input", role="checkbox", name="Analytics cookies", input_type="checkbox",
                                in_consent=True),
     "cookie_refusal", UBS, "control_type"),
    # Links
    ("next_other_domain", link("Next", "http://evil.invalid/list?page=2"), "pagination", UBS, "link_target"),
    ("www_is_same_site", link("Next", "https://bcn.ch/la-bcn/carrieres/postes-ouverts?page=2"),
     "pagination", BCN, None),
    ("mailto", link("Next", "mailto:hr@example.com"), "pagination", UBS, "link_target"),
    ("tel", link("2", "tel:+41000000000"), "pagination", UBS, "link_target"),
    ("download_attr", link("Next", UBS + "&page=2", download=True), "pagination", UBS, "link_target"),
    ("target_blank", link("Next", UBS + "&page=2", target="_blank"), "pagination", UBS, "link_target"),
    ("javascript_link", link("Load more", "javascript:void(0)"), "pagination", UBS, None),
    # Sort, filter, language
    ("trier_par", button("Trier par date"), "pagination", UBS, "not_pagination"),
    ("filtres", button("Filtres"), "pagination", UBS, "not_pagination"),
    ("reset_filters", button("Reset"), "pagination", UBS, "not_pagination"),
    ("language", button("Language"), "pagination", UBS, "not_pagination"),
    ("expanded_toggle", button("Show more options", aria_expanded=False), "pagination", UBS, "not_pagination"),
    ("ok_as_pagination", button("OK"), "pagination", UBS, "acceptance_word"),
    ("continue_without_accepting_as_pagination", button("Continuer sans accepter"), "pagination", UBS,
     "not_pagination"),
    ("nur_notwendige_as_pagination", button("Nur notwendige"), "pagination", UBS, "not_pagination"),
    # Cookie consent
    ("alle_ablehnen", button("Alle ablehnen", in_consent=True), "cookie_refusal", UBS, None),
    ("nur_notwendige", button("Nur notwendige Cookies", in_consent=True), "cookie_refusal", UBS, None),
    ("rifiuta_tutto", button("Rifiuta tutto", in_consent=True), "cookie_refusal", UBS, None),
    ("continuer_sans_accepter", button("Continuer sans accepter", in_consent=True), "cookie_refusal", UBS, None),
    ("essential_only", button("Essential Only", in_consent=True), "cookie_refusal", UBS, None),
    ("privacy_link_as_refusal", link("privacy statement", UBS, in_consent=True), "cookie_refusal", UBS,
     "not_refusal"),
    ("decline_outside_consent", button("Decline"), "cookie_refusal", UBS, "purpose_mismatch"),
    ("einstellungen", button("Einstellungen", in_consent=True), "cookie_refusal", UBS, "preferences"),
    ("accept_terms_and_apply", button("Accept terms and apply", in_consent=True), "cookie_acceptance", UBS,
     "forbidden_action"),       # acceptance_fallback=True below
    ("refusal_as_acceptance", button("Decline all", in_consent=True), "cookie_acceptance", UBS,
     "acceptance_not_allowed"),  # acceptance_fallback=True below
]

WITH_FALLBACK = {"rolex_accepter_tous_with_fallback", "accept_terms_and_apply", "refusal_as_acceptance"}


@pytest.mark.parametrize("case_id, control, purpose, page_url, expected",
                         REAL_CASES + SYNTHETIC_CASES, ids=[c[0] for c in REAL_CASES + SYNTHETIC_CASES])
def test_rule(case_id, control, purpose, page_url, expected):
    refusal = check(control, purpose, site_host(page_url), acceptance_fallback=case_id in WITH_FALLBACK)
    assert (refusal.reason if refusal else None) == expected, refusal


def test_acceptance_needs_the_fallback_flag():
    accept = button("Accepter tous les cookies", in_consent=True)
    assert check(accept, "cookie_acceptance", site_host(ROLEX)).reason == "acceptance_not_allowed"
    assert check(accept, "cookie_acceptance", site_host(ROLEX), acceptance_fallback=True) is None


def test_known_gap_filter_without_keyword_or_aria():
    """Lombard Odier 'Location' is a filter with no ARIA hint and no general keyword.

    No general rule can recognise it: the rules allow it, the agent must not choose it,
    and step 4 stops when a click brings no new offers.
    """
    assert check(button("Location"), "pagination", site_host(LO)) is None


def test_acceptance_pending_needs_the_fallback_and_an_acceptance_control():
    from job_watch.web.click_rules import acceptance_pending
    accept = Control(tag="button", role="button", text="Accept all", name="Accept all", in_consent=True)
    nxt = Control(tag="a", role="link", text="Next", name="Next", href="https://jobs.example.com/list?page=2")
    assert acceptance_pending([nxt, accept], "jobs.example.com", True)
    assert not acceptance_pending([nxt, accept], "jobs.example.com", False)
    assert not acceptance_pending([nxt], "jobs.example.com", True)

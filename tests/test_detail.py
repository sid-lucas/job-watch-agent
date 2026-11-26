"""Detail phase: choice of the offers whose page is opened (no LLM, no browser)."""
from job_watch.list_agent.detail import plan_details
from job_watch.list_agent.extraction import CheckedOffer

LIST = "https://jobs.example.com/list"


def offer(key, link=""):
    return CheckedOffer(title=f"Offer {key}", location="Geneva", link=link, reference="", verified=bool(link),
                        key=key)


def reasons(plan):
    return {s.key: s.reason for s in plan.skipped}


def test_only_new_kept_offers_with_their_own_same_site_link_are_opened():
    offers = [offer("a", "https://jobs.example.com/a"),          # opened
              offer("b", "https://jobs.example.com/b"),          # already known
              offer("c", "https://jobs.example.com/c"),          # not kept by the filter
              offer("d"),                                        # no link
              offer("e", "https://evil.example/e"),              # other site
              offer("f", "https://jobs.example.com/all"),        # shared link
              offer("g", "https://jobs.example.com/all"),
              offer("h", "https://www.jobs.example.com/h")]      # www. is the same site
    plan = plan_details(offers, new_keys=list("acdefgh"), kept_keys=list("abdefgh"), list_url=LIST)
    assert [o.key for o in plan.to_open] == ["a", "h"]
    assert reasons(plan) == {"b": "not_new", "c": "not_kept", "d": "no_link", "e": "other_site",
                             "f": "shared_link", "g": "shared_link"}


def test_the_budget_keeps_the_first_offers_in_page_order():
    offers = [offer(str(n), f"https://jobs.example.com/{n}") for n in range(5)]
    keys = [o.key for o in offers]
    plan = plan_details(offers, new_keys=keys, kept_keys=keys, list_url=LIST, budget=3)
    assert [o.key for o in plan.to_open] == ["0", "1", "2"]
    assert reasons(plan) == {"3": "budget", "4": "budget"}


def answer(**fields):
    from helpers import offer_detail
    return offer_detail(**fields)


def test_check_detail_keeps_only_what_the_page_supports():
    from datetime import date
    from job_watch.list_agent.detail import check_detail
    page = "Cloud Engineer\nZurich, 80-100 %\n5 years of experience with Kubernetes\nFluent in German"
    checked = check_detail("k", page, answer(
        requirements=["5 years of experience with kubernetes", "PhD in physics"],   # second one invented
        workload="80-100 %", posted="2026-11-20",
        languages=[{"language": "de", "level": "required"}, {"language": "de", "level": "required"},
                   {"language": "en", "level": "required"}]), date(2026, 11, 25))
    assert checked.requirements == ["5 years of experience with Kubernetes"]       # exact page text
    assert checked.dropped_requirements == 1
    assert checked.workload == "80-100 %" and checked.posted == "2026-11-20"
    assert checked.languages == [{"language": "de", "level": "required"}]         # English is not in the page


def test_invented_workload_and_implausible_dates_are_emptied():
    from datetime import date
    from job_watch.list_agent.detail import check_detail
    today = date(2026, 11, 25)
    for posted in ("2027-01-01", "1999-12-31", "20 November 2026", ""):
        assert check_detail("k", "Text", answer(posted=posted, workload="100 %"), today).posted == ""
    assert check_detail("k", "Text", answer(workload="100 %"), today).workload == ""


def test_closed_lists_and_no_score_field():
    import pytest
    from pydantic import ValidationError
    from job_watch.list_agent.detail import OfferDetail
    with pytest.raises(ValidationError):
        answer(contract="CEO with bonus")
    parsed = OfferDetail.model_validate({**answer().model_dump(), "score": 100})  # extra key ignored
    assert "score" not in parsed.model_dump()


def test_a_contract_not_stated_in_the_page_becomes_unknown():
    from datetime import date
    from job_watch.list_agent.detail import check_detail, contract_stated
    today = date(2026, 11, 25)
    page = "Security Analyst\nGeneva, internship of 6 months"
    wrong = check_detail("k", page, answer(contract="permanent"), today)
    assert (wrong.contract, wrong.contract_doubtful) == ("unknown", True)
    right = check_detail("k", page, answer(contract="internship"), today)
    assert (right.contract, right.contract_doubtful) == ("internship", False)
    assert contract_stated("permanent", "Contrat à durée indéterminée (CDI)")
    assert contract_stated("fixed_term", "Befristete Stelle, befristet auf 12 Monate")
    assert not contract_stated("fixed_term", "unbefristet")            # whole words only
    assert contract_stated("apprenticeship", "Lehrstelle als Informatiker EFZ")
    assert contract_stated("unknown", "")


def test_an_offer_page_on_another_subdomain_of_the_list_domain_is_opened():
    offers = [offer("a", "https://jobs.example.com/a"), offer("b", "https://evil.example.org/b")]
    plan = plan_details(offers, new_keys=["a", "b"], kept_keys=["a", "b"],
                        list_url="https://careers.example.com/list")
    assert [o.key for o in plan.to_open] == ["a"] and reasons(plan) == {"b": "other_site"}


PAGE = """Junior Security Engineer
Genève, Suisse - 100 %, CDI
Votre profil
- Bachelor HES en informatique ou titre jugé équivalent
- Au moins 3 ans d'expérience en sécurité
- Français courant, l'allemand est un atout
- Salaire : CHF 90'000 - 100'000
"""


def test_the_fact_sheet_keeps_facts_stated_in_the_page():
    from datetime import date
    from job_watch.list_agent.detail import check_detail
    checked = check_detail("k", PAGE, answer(
        category="Cybersecurity engineering/architecture/pentest", city="Geneve", country="Suisse",
        seniority="junior", experience_years=3, experience_requirement="required",
        languages=[{"language": "fr", "level": "required"}, {"language": "de", "level": "required"}],
        contract="permanent", workload="100 %", salary="CHF 90'000 - 100'000", education="HES-university"),
        date(2026, 11, 26))
    assert (checked.city, checked.country) == ("Genève", "Suisse")                 # exact page text
    assert checked.seniority == "junior" and checked.education == "HES-university"
    assert (checked.experience_years, checked.experience_requirement) == (3, "required")    # "au moins"
    assert checked.languages == [{"language": "fr", "level": "required"},          # "courant"
                                 {"language": "de", "level": "nice_to_have"}]      # "un atout": the page wins
    assert checked.contract == "permanent" and checked.salary == "CHF 90'000 - 100'000"
    assert checked.unchecked == []


def test_facts_the_page_does_not_state_become_unknown():
    from datetime import date
    from job_watch.list_agent.detail import check_detail
    checked = check_detail("k", PAGE, answer(
        city="Lausanne", country="France", seniority="senior", experience_years=7, experience_requirement="required",
        languages=[{"language": "it", "level": "required"}], education="CFC", salary="CHF 150'000"),
        date(2026, 11, 26))
    assert (checked.city, checked.country, checked.seniority, checked.education) == (
        "unknown", "unknown", "unknown", "unknown")
    assert (checked.experience_years, checked.experience_requirement) == (None, "unknown")    # "7 years" not there
    assert checked.languages == [] and checked.salary == ""
    assert set(checked.unchecked) == {"city", "country", "seniority", "education", "experience_years"}


def test_a_language_level_without_words_around_it_is_unknown():
    from job_watch.list_agent.detail import checked_languages, LanguageNeed
    page = "Our team works in English. You will join the Geneva office."
    assert checked_languages([LanguageNeed(language="en", level="required")], page) == [
        {"language": "en", "level": "unknown"}]


def test_experience_years_need_a_word_for_years_next_to_the_number():
    from job_watch.list_agent.detail import checked_experience
    assert checked_experience(5, "5+ years of experience, ideally in a bank") == (5, "preferred")
    assert checked_experience(3, "3-5 Jahre Erfahrung, mindestens") == (3, "required")
    assert checked_experience(2, "Team of 2 people, 10 years old company") == (None, "unknown")
    assert checked_experience(None, "5 years") == (None, "unknown")


def test_education_codes_are_upper_case_whole_words():
    from job_watch.list_agent.detail import education_stated
    assert education_stated("CFC", "CFC d'informaticien ou titre équivalent")
    assert education_stated("ES", "Diplôme ES ou HF en informatique")
    assert not education_stated("ES", "Tests, es ist gut")                    # "es" in German text
    assert education_stated("HES-university", "Master degree in computer science")

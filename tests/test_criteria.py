"""Criteria (offers/criteria.py): validation of the settings, checks of the answers, score. No LLM."""
import runpy
from datetime import date

import pytest

from job_watch import config
from job_watch.offers.criteria import Answer, check_answers, judge, load_settings, quote_in

POINTS = {"ask": "Is the job in Geneva?", "points": 15, "group": "location"}
REJECT = {"ask": "Is the job abroad?", "reject": True}


def error(profile="Short profile", criteria=(POINTS,), code_criteria=(), kept_domains=("Technology/IT",)) -> str:
    with pytest.raises(SystemExit) as raised:
        load_settings(profile, list(criteria), list(code_criteria), list(kept_domains))
    return str(raised.value)


def test_valid_settings_are_loaded():
    settings = load_settings("Short profile", [POINTS, REJECT, {"ask": "No experience asked?", "points": 10,
                                                                "absence": True}],
                             [{"type": "company_in", "names": ["Pictet"], "points": 20, "group": "company"},
                              {"type": "posted_older_than_days", "days": 30, "points": -5}],
                             ["Technology/IT", "Other", "Other"])
    assert [c.points for c in settings.criteria] == [15, None, 10]
    assert settings.criteria[1].reject and settings.criteria[2].absence
    assert [c.type for c in settings.code_criteria] == ["company_in", "posted_older_than_days"]
    assert settings.kept_domains == ["Technology/IT", "Other"]


def test_the_example_config_is_valid():
    example = runpy.run_path(str(config.BASE_DIR / "user_config.example.py"))
    assert load_settings(example["PROFILE"], example["CRITERIA"], example["CODE_CRITERIA"],
                         example["KEPT_DOMAINS"]).criteria


@pytest.mark.parametrize("criterion, expected", [
    ({"points": 5}, "CRITERIA[0] ask: missing key"),
    ({"ask": "  ", "points": 5}, "CRITERIA[0]"),
    ({"ask": "Q?"}, 'exactly one of them'),
    ({"ask": "Q?", "reject": True, "points": 5}, 'exactly one of them'),
    ({"ask": "Q?", "points": 0}, '"points" must not be 0'),
    ({"ask": "Q?", "reject": False}, "reject"),
    ({"ask": "Q?", "reject": True, "group": "g"}, '"group" only applies'),
    ({"ask": "Q?", "reject": True, "absence": True}, '"absence" only applies'),
    ({"ask": "Q?", "point": 5}, "point: unknown key (typo?)"),
])
def test_a_bad_criterion_is_named_in_the_error(criterion, expected):
    message = error(criteria=[criterion])
    assert message.startswith("Invalid user_config.py:") and expected in message


def test_the_same_question_twice_is_refused():
    assert "asked twice" in error(criteria=[POINTS, {**POINTS, "ask": " is the job in geneva? "}])


@pytest.mark.parametrize("profile", ["", "x" * 1001, None])
def test_the_profile_is_a_short_text(profile):
    assert "PROFILE" in error(profile=profile)


def test_criteria_must_not_be_empty():
    assert "CRITERIA" in error(criteria=[])


@pytest.mark.parametrize("code_criterion, expected", [
    ({"type": "salary_above", "points": 5}, 'CODE_CRITERIA[0]'),
    ({"names": ["Pictet"], "points": 5}, 'missing or unknown "type"'),
    ({"type": "company_in", "names": [], "points": 5}, "names"),
    ({"type": "company_in", "names": [""], "points": 5}, "names"),
    ({"type": "company_in", "names": ["Pictet"]}, "exactly one of them"),
    ({"type": "posted_older_than_days", "days": 0, "points": -5}, "days"),
    ({"type": "posted_older_than_days", "days": 30, "points": -5, "names": ["x"]}, "unknown key"),
])
def test_a_bad_code_criterion_is_named_in_the_error(code_criterion, expected):
    assert expected in error(code_criteria=[code_criterion])


@pytest.mark.parametrize("kept_domains, expected", [
    ([], "KEPT_DOMAINS"),
    (["Technology/IT", "IT"], "KEPT_DOMAINS: unknown domains ['IT']"),
    (["technology/it"], "unknown domains"),
])
def test_kept_domains_are_known_triage_domains(kept_domains, expected):
    assert expected in error(kept_domains=kept_domains)


# ---------- score of one offer ----------

TODAY = date(2026, 11, 26)
AD = """Security Analyst SOC (junior)
Lieu : Genève, Suisse. Taux d'activité : 80-100 %.
Vous rejoignez notre centre opérationnel de sécurité."""
SETTINGS = load_settings("Short profile", [
    {"ask": "Is the job abroad?", "reject": True},                                         # c1
    {"ask": "Is it a SOC job?", "points": 25, "group": "job type"},                        # c2
    {"ask": "Is it another security job?", "points": 20, "group": "job type"},             # c3
    {"ask": "Is it explicitly junior?", "points": 20},                                     # c4
    {"ask": "No experience asked at all?", "points": 10, "group": "experience", "absence": True},  # c5
    {"ask": "Exactly 3 years asked?", "points": -5, "group": "experience"},                # c6
    {"ask": "Is the job in Geneva?", "points": 15},                                        # c7
], [
    {"type": "company_in", "names": ["Pictet", "Lombard Odier"], "points": 20, "group": "company"},
    {"type": "company_in", "names": ["UBS", "Lombard"], "points": 10, "group": "company"},
    {"type": "posted_older_than_days", "days": 30, "points": -5},
], ["Technology/IT"])


def answers(**given) -> list[Answer]:
    """answers(c2=("yes", "quote")) -> the raw answers of the LLM."""
    return [Answer(id=key, answer=value, quote=quote) for key, (value, quote) in given.items()]


def verdict(raw, text=AD, detail_read=True, company="", posted=None):
    checked = check_answers(SETTINGS, raw, text, detail_read)
    return judge(SETTINGS, checked, company, posted, TODAY), checked


@pytest.mark.parametrize("quote, found", [
    ("Genève, Suisse", True),
    ("  lieu :   GENÈVE,\nsuisse ", True),       # case and whitespace ignored
    ("Geneva", False),                          # not a translation: the exact text
    ("SOC", True),
    ("de", False),                              # too short to prove anything
    ("x" * 301, False),
    ("", False),
])
def test_a_quote_must_be_in_the_text(quote, found):
    assert quote_in(quote, AD) is found


def test_a_yes_with_a_quote_found_gives_its_points_and_shows_the_quote():
    result, checked = verdict(answers(c4=("yes", "SOC (junior)"), c7=("yes", "Genève")))
    assert result.status == "new" and result.score == 35
    assert result.reasons == ["Is it explicitly junior? (+20): 'SOC (junior)'", "Is the job in Geneva? (+15): 'Genève'"]
    assert [a.answer for a in checked] == ["unknown", "unknown", "unknown", "yes", "unknown", "unknown", "yes"]


def test_a_yes_whose_quote_is_not_in_the_text_becomes_unknown():
    result, checked = verdict(answers(c7=("yes", "Geneva city centre"), c4=("yes", "")))
    assert result.score == 0 and result.reasons == []
    assert checked[6].answer == "unknown" and checked[6].quote == "Geneva city centre" and not checked[6].quote_found
    assert checked[3].answer == "unknown"


def test_a_reject_criterion_answered_yes_rejects_whatever_the_points():
    result, _ = verdict(answers(c1=("yes", "Lieu : Genève"), c2=("yes", "SOC")))
    assert result.status == "rejected" and result.score == 0
    assert result.reasons == ["rejected: Is the job abroad? | 'Lieu : Genève'"]


def test_a_reject_without_valid_quote_never_rejects():
    result, _ = verdict(answers(c1=("yes", "Paris, France")))
    assert result.status == "new"


def test_no_and_unknown_never_reject_nor_give_points():
    result, _ = verdict(answers(c1=("no", ""), c2=("unknown", "SOC"), c7=("no", "Genève")))
    assert result.status == "new" and result.score == 0 and result.reasons == []


def test_only_the_best_yes_of_a_group_counts():
    result, _ = verdict(answers(c2=("yes", "centre opérationnel de sécurité"), c3=("yes", "Security Analyst")))
    assert result.score == 25 and len(result.reasons) == 1 and result.reasons[0].startswith("Is it a SOC job? (+25)")


def test_the_best_of_a_group_can_be_a_penalty_when_it_is_the_only_yes():
    settings_ad = AD + "\n3 ans d'expérience exigés."
    result, _ = verdict(answers(c6=("yes", "3 ans d'expérience")), text=settings_ad)
    assert result.score == -5


def test_unknown_ids_are_ignored_and_the_first_answer_per_id_wins():
    raw = answers(c7=("yes", "Genève")) + [Answer(id="c7", answer="no"), Answer(id="c99", answer="yes", quote="SOC"),
                                          Answer(id="Is it a SOC job?", answer="yes", quote="SOC")]
    result, _ = verdict(raw)
    assert result.score == 15


# ---------- absence criteria ----------

def test_an_absence_counts_without_quote_when_the_full_ad_was_read():
    result, _ = verdict(answers(c5=("yes", "")), detail_read=True)
    assert result.score == 10 and result.reasons == ["No experience asked at all? (+10): 'absent from the ad'"]


def test_an_absence_never_counts_when_the_full_ad_was_not_read():
    """Detail page not opened (listing data only), or truncated: the ad may state it further down."""
    result, checked = verdict(answers(c5=("yes", "")), text="Security Analyst SOC", detail_read=False)
    assert result.score == 0 and checked[4].answer == "unknown"


def test_an_absence_with_a_quote_not_in_the_ad_does_not_count():
    result, _ = verdict(answers(c5=("yes", "no experience needed")))
    assert result.score == 0


def test_an_absence_is_contradicted_by_another_yes_of_its_group():
    text = AD + "\n3 ans d'expérience exigés."
    result, _ = verdict(answers(c5=("yes", ""), c6=("yes", "3 ans d'expérience")), text=text)
    assert result.score == -5 and result.reasons == ["Exactly 3 years asked? (-5): \"3 ans d'expérience\""]


# ---------- code criteria ----------

def test_company_in_matches_whole_names_and_the_best_of_the_group_counts():
    assert verdict([], company="Banque Lombard Odier & Co")[0].score == 20     # top list beats "Lombard" (+10)
    assert verdict([], company="UBS Switzerland AG")[0].reasons == ["company in list (+10): 'UBS'"]
    assert verdict([], company="SUBSEA Ltd")[0].score == 0                     # not a whole name


def test_posted_older_than_days_needs_a_known_date():
    assert verdict([], posted=date(2026, 10, 1))[0].reasons == ["posted over 30 days ago (-5): '2026-10-01'"]
    assert verdict([], posted=date(2026, 10, 27))[0].score == 0                # exactly 30 days: not over
    assert verdict([], posted=None)[0].score == 0


def test_llm_and_code_criteria_add_up():
    result, _ = verdict(answers(c2=("yes", "SOC"), c7=("yes", "Genève")), company="Pictet", posted=date(2026, 9, 1))
    assert result.score == 25 + 15 + 20 - 5


# ---------- reasons shown ----------

def test_a_reason_shows_the_label_or_the_question_cut_then_the_quote_cut():
    settings = load_settings("Short profile", [
        {"ask": "Is the main workplace in Geneva (the city, not the canton)?", "points": 15, "label": "Geneva"},
        {"ask": "Does the ad explicitly describe the position as junior, graduate or entry-level?", "points": 20},
    ], [], ["Technology/IT"])
    long_quote = "junior " + "x" * 300
    text = f"Lieu : Genève\n{long_quote}"
    checked = check_answers(settings, [Answer(id="c1", answer="yes", quote="Genève"),
                                       Answer(id="c2", answer="yes", quote=long_quote[:290])], text, True)
    reasons = judge(settings, checked, "", None, TODAY).reasons
    assert reasons[0] == "Geneva (+15): 'Genève'"
    label, quote = reasons[1].split(" (+20): ")
    assert label == "Does the ad explicitly describe the position as…" and len(label) <= 50
    assert len(quote) <= 152 and quote.endswith("…'")


def test_a_label_is_short():
    assert "label" in error(criteria=[{**POINTS, "label": "x" * 51}])

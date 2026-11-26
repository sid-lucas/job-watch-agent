"""Validation of PROFILE, CRITERIA and CODE_CRITERIA (offers/criteria.py). No LLM."""
import runpy

import pytest

from job_watch import config
from job_watch.offers.criteria import load_settings

POINTS = {"ask": "Is the job in Geneva?", "points": 15, "group": "location"}
REJECT = {"ask": "Is the job abroad?", "reject": True}


def error(profile="Short profile", criteria=(POINTS,), code_criteria=()) -> str:
    with pytest.raises(SystemExit) as raised:
        load_settings(profile, list(criteria), list(code_criteria))
    return str(raised.value)


def test_valid_settings_are_loaded():
    settings = load_settings("Short profile", [POINTS, REJECT, {"ask": "No experience asked?", "points": 10,
                                                                "absence": True}],
                             [{"type": "company_in", "names": ["Pictet"], "points": 20, "group": "company"},
                              {"type": "posted_older_than_days", "days": 30, "points": -5}])
    assert [c.points for c in settings.criteria] == [15, None, 10]
    assert settings.criteria[1].reject and settings.criteria[2].absence
    assert [c.type for c in settings.code_criteria] == ["company_in", "posted_older_than_days"]


def test_the_example_config_is_valid():
    example = runpy.run_path(str(config.BASE_DIR / "user_config.example.py"))
    assert load_settings(example["PROFILE"], example["CRITERIA"], example["CODE_CRITERIA"]).criteria


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

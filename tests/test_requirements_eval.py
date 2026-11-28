"""evals/check_requirements.py: the comparison with the frozen output (no LLM)."""
from evals.check_requirements import Score, pair
from job_watch.matching.requirements import Requirement


def req(label, quote, kind="must", category="skill", options=(), min_years=None):
    return {"label": label, "quote": quote, "kind": kind, "category": category, "options": list(options),
            "min_years": min_years, "level": ""}


EXPECTED = [
    req("Java", "Vous maîtrisez Java et Spring"),
    req("Spring", "Vous maîtrisez Java et Spring", category="tool"),
    req("Cloud certification", "certification AWS ou Azure", kind="nice", options=["AWS", "Azure"]),
    req("3 years experience", "3-5 years of experience", category="experience", min_years=3),
    req("French", "French is an asset", kind="nice", category="language"),
]


def test_pairs_by_label_then_by_quote_each_found_one_used_once():
    got = [Requirement(**req("Spring Framework", "Vous maîtrisez Java et Spring", category="tool")),
           Requirement(**req("java", "Vous maîtrisez Java et Spring"))]
    pairs = pair(EXPECTED[:2], got)
    assert [found.label if found else None for _, found in pairs] == ["java", "Spring Framework"]
    assert pair(EXPECTED[1:2], got[1:]) == [(EXPECTED[1], None)]      # same quote, other thing: not paired


def test_score_counts_recall_kind_alternatives_years_and_extras():
    got = [Requirement(**r) for r in [
        req("Java", "Vous maîtrisez Java et Spring"),
        req("AWS certification", "certification AWS ou Azure", kind="must"),          # split, kind wrong
        req("3 years experience", "3-5 years of experience", category="experience", min_years=5),
        req("French", "French is an asset", kind="nice", category="language"),
        req("Team player", "You are a team player", category="soft_skill")]]          # not expected
    score = Score().add(EXPECTED, got)
    assert (score.must_found, score.must) == (2, 3)          # Spring missing
    assert (score.kind_ok, score.found) == (3, 4)
    assert (score.options_ok, score.options) == (0, 1)
    assert (score.years_ok, score.years) == (0, 1)
    assert score.extra == 1
    assert score.line() == "must found 2/3, kind 3/4, alternatives 0/1, min_years 0/1, extra 1"

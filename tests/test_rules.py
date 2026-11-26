"""Rules engine: dealbreakers and bonuses applied by code to facts (no LLM)."""
import pytest
from pydantic import ValidationError

from job_watch import config
from job_watch.offers import rules
from job_watch.offers.rules import Rule, applies, facts_of, judge, seniority_in

TECH = "Technology/IT"


@pytest.fixture(autouse=True)
def user_rules(monkeypatch):
    monkeypatch.setattr(config, "KEPT_DOMAINS", [TECH, "Other"])
    monkeypatch.setattr(config, "DEALBREAKERS", [
        {"name": "abroad", "fact": "location", "is": "abroad"},
        {"name": "senior level", "fact": "seniority", "in": ["senior", "lead"]},
        {"name": "German required", "fact": "languages_required", "contains": "de"},
        {"name": "more than 5 years required", "fact": "experience_years_required", "above": 5},
    ])
    monkeypatch.setattr(config, "BONUSES", [
        {"name": "security job", "fact": "category", "in": ["Cybersecurity SOC/incident response"], "points": 30},
        {"name": "entry level", "fact": "seniority", "in": ["graduate", "junior"], "points": 30},
        {"name": "Geneva", "fact": "city", "matches": r"gen[eè]v|geneva", "points": 20},
        {"name": "top company", "fact": "company", "in_names": ["Lombard Odier"], "points": 20},
        {"name": "internship", "fact": "contract", "is": "internship", "points": -10},
    ])


def facts(**values):
    base = {"domain": TECH, "title": "Analyst", "company": "Bank"}
    return facts_of({**base, **values})


def test_bonuses_add_up_with_their_details():
    verdict = judge(facts(category="Cybersecurity SOC/incident response", seniority="junior", city="Genève",
                          company="Banque Lombard Odier & Cie", contract="internship"))
    assert verdict.status == "new" and verdict.score == 30 + 30 + 20 + 20 - 10
    assert verdict.reasons == ["security job (+30)", "entry level (+30)", "Geneva (+20)", "top company (+20)",
                               "internship (-10)"]


@pytest.mark.parametrize("values, reason", [
    ({"domain": "Finance, banking & accounting"}, "domain not kept"),
    ({"city": "Singapore"}, "abroad"),
    ({"title": "Senior Security Engineer"}, "senior level"),                    # seniority from the title
    ({"languages": [{"language": "de", "level": "required"}]}, "German required"),
    ({"experience_years": 8, "experience_requirement": "required"}, "more than 5 years required"),
])
def test_dealbreakers_reject_with_the_reason(values, reason):
    verdict = judge(facts(**values))
    assert verdict.status == "rejected" and verdict.score == 0
    assert verdict.reasons[0].startswith(f"rejected: {reason} (")


@pytest.mark.parametrize("values", [
    {"domain": None},                                                           # no valid triage answer
    {"domain": "Other"},                                                        # no clue in the title: kept
    {"city": "unknown", "country": "unknown", "location": "unknown"},
    {"seniority": "unknown", "title": "Analyst"},
    {"languages": [{"language": "de", "level": "nice_to_have"}]},               # a plus, not required
    {"languages": [{"language": "de", "level": "unknown"}]},
    {"experience_years": 8, "experience_requirement": "preferred"},             # not stated as required
    {"experience_years": None, "experience_requirement": "required"},
])
def test_an_unknown_fact_never_rejects(values):
    assert judge(facts(**values)).status == "new"


def test_an_unknown_fact_never_gives_points():
    assert judge(facts(city="unknown", seniority="unknown", contract="unknown")).score == 0


def test_in_names_matches_whole_words_and_an_empty_list_matches_nothing():
    rule = Rule(name="top", fact="company", in_names=["UBS"], points=10)
    assert applies(rule, {"company": "UBS Switzerland AG"}) and not applies(rule, {"company": "Clubsport"})
    assert not applies(Rule(name="none", fact="company", in_names=[], points=10), {"company": "UBS"})


@pytest.mark.parametrize("rule", [
    {"name": "typo", "fact": "senority", "is": "senior"},                       # unknown fact
    {"name": "two operators", "fact": "seniority", "is": "senior", "in": ["lead"]},
    {"name": "no operator", "fact": "seniority"},
    {"name": "bad regex", "fact": "city", "matches": "("},
    {"name": "unknown key", "fact": "city", "is": "Geneva", "weight": 3},
])
def test_invalid_rules_are_refused_with_a_clear_message(rule):
    with pytest.raises(ValidationError):
        Rule(**rule)


def test_a_bonus_without_points_is_refused(monkeypatch):
    monkeypatch.setattr(config, "BONUSES", [{"name": "x", "fact": "city", "is": "Geneva"}])
    with pytest.raises(ValueError, match="without points"):
        rules.bonuses()


@pytest.mark.parametrize("title, level", [
    ("Senior Security Engineer", "senior"), ("Lead Developer", "lead"), ("Head of IT", "lead"),
    ("Junior SOC Analyst", "junior"), ("Graduate Programme - IT", "graduate"), ("Jeune diplômé IT", "graduate"),
    ("Senior Team Lead", "lead"), ("Security Engineer", "unknown"), ("Leadership trainer", "unknown"),
])
def test_seniority_from_words(title, level):
    assert seniority_in(title) == level


def test_facts_of_an_rss_offer():
    found = facts_of({"title": "Pentester", "company": "X", "source": "swissdevjobs", "location": "unknown",
                      "description": "Wir suchen und bieten dir eine spannende Stelle mit der du die Sicherheit "
                                     "unserer Kunden verbesserst und für die wir eine Person suchen die mit uns ist",
                      "domain": TECH})
    assert found["location"] == "unknown" and found["ad_language"] == "de" and found["seniority"] == "unknown"


def test_the_detail_location_wins_over_the_listed_one():
    assert facts(city="Zurich", location="London, United Kingdom")["location"] == "switzerland"
    assert facts(city="unknown", country="unknown", location="Remote - Germany")["location"] == "abroad"


def test_the_default_rules_are_valid(monkeypatch):
    monkeypatch.setattr(config, "DEALBREAKERS", config.DEFAULT_DEALBREAKERS)
    monkeypatch.setattr(config, "BONUSES", config.DEFAULT_BONUSES)
    assert len(rules.dealbreakers()) == len(config.DEFAULT_DEALBREAKERS) + 1 and rules.bonuses()


# ---------- listed offers ----------

def listed(title, location, domain=TECH):
    from job_watch.list_agent.extraction import CheckedOffer
    return CheckedOffer(title=title, location=location, link="", reference="", verified=False, key="k", domain=domain)


def test_listing_dealbreakers_use_the_facts_known_from_the_list():
    from job_watch.offers.rules import listing_rejections
    assert listing_rejections(listed("Security Engineer", "Geneva"), "Bank") == []
    assert listing_rejections(listed("Security Engineer", "Gossau"), "Bank") == []          # unknown town: kept
    assert listing_rejections(listed("Security Engineer", "Remote"), "Bank") == []
    assert listing_rejections(listed("Something", "Geneva", "Other"), "Bank") == []          # no clue: kept
    assert listing_rejections(listed("Something", "Geneva", None), "Bank") == []             # no valid answer
    assert listing_rejections(listed("Security Engineer", "Singapore"), "Bank")[0].startswith("rejected: abroad")
    assert listing_rejections(listed("Client Advisor", "Geneva", "Finance, banking & accounting"),
                              "Bank")[0].startswith("rejected: domain not kept")
    assert listing_rejections(listed("Senior Developer", "Zurich"), "Bank")[0].startswith("rejected: senior level")


def test_kept_follows_the_listing_rejections():
    from job_watch.offers.rules import kept
    offer = listed("Security Engineer", "Geneva")
    assert kept(offer)
    offer.rejected_by = ["rejected: abroad (location='abroad')"]
    assert not kept(offer)

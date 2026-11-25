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

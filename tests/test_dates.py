"""Publication date read from a relative date of the page (no LLM)."""
from datetime import date

import pytest

from job_watch.offers.dates import posted_in_text

READ = date(2026, 11, 27)


@pytest.mark.parametrize("text, days", [
    ("posted on | Posted 13 Days Ago | job requisition id", 13),
    ("Posted 1 day ago", 1),
    ("Posted Today", 0),
    ("Posted Yesterday", 1),
    ("3 weeks ago", 21),
    ("Publiée il y a 5 jours", 5),
    ("il y a 2 semaines", 14),
    ("Publié aujourd'hui", 0),
    ("Publiée hier", 1),
    ("Vor 4 Tagen veröffentlicht", 4),
    ("vor 1 Tag", 1),
    ("vor 2 Wochen", 14),
    ("Veröffentlicht gestern", 1),
    ("1 month ago", 30),
])
def test_a_relative_date_is_counted_back_from_the_day_the_page_was_read(text, days):
    assert (READ - posted_in_text(text, READ)).days == days


@pytest.mark.parametrize("text", [
    "Posted 30+ Days Ago",                  # only a lower bound
    "5 years of experience",                # not a date
    "Il y a 3 ans d'expérience",            # "ans" is not a unit of the list
    "Apply before 12.12.2026",              # an absolute date is not read here
    "Yesterday's news",
    "",
])
def test_no_date_when_the_page_gives_none(text):
    assert posted_in_text(text, READ) is None


def test_the_first_relative_date_of_the_page_is_the_offer_s_own():
    page = "ML Engineer\nPosted 3 Days Ago\n...\nSimilar jobs\nData Engineer\nPosted 29 Days Ago"
    assert posted_in_text(page, READ) == date(2026, 11, 24)
    assert posted_in_text("Posted 30+ Days Ago\nSimilar jobs\nPosted 2 Days Ago", READ) is None

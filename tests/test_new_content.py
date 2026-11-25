"""Unit tests of the new-content diff, without browser."""
from job_watch.web.new_content import new_lines, page_lines

HEADER = ["Careers", "Open positions", "Search", "Filters", "Sort by date"]
FOOTER = ["Privacy", "Terms of use", "Cookies", "Contact", "© Company"]


def offer(n, city="Geneva"):
    return [f"Offer {n}", city, "Posted 3 days ago"]


def test_first_observation_is_all_new():
    assert new_lines([], ["a", "b"]) == ["a", "b"]


def test_same_page_has_nothing_new():
    page = HEADER + offer(1) + offer(2) + FOOTER
    assert new_lines(page, page) == []


def test_load_more_keeps_only_the_appended_offers_with_their_repeated_lines():
    before = HEADER + offer(1) + offer(2) + ["Load more"] + FOOTER
    after = HEADER + offer(1) + offer(2) + offer(3) + offer(4) + ["Load more"] + FOOTER
    assert new_lines(before, after) == offer(3) + offer(4)


def test_page_replaced_in_place_keeps_lines_shared_with_the_previous_page():
    # Pagination without URL change (Workday): "Geneva" and "Posted 3 days ago" repeat
    before = HEADER + offer(1) + offer(2) + offer(3) + ["page 1 of 2"] + FOOTER
    after = HEADER + offer(4) + offer(5) + offer(6) + ["page 2 of 2"] + FOOTER
    assert new_lines(before, after) == offer(4) + offer(5) + offer(6) + ["page 2 of 2"]


def test_counter_change_far_from_the_new_offers_is_a_separate_region():
    before = ["Showing 6 of 9"] + HEADER + [line for n in range(1, 7) for line in offer(n)] + FOOTER
    after = (["Showing 9 of 9"] + HEADER + [line for n in range(1, 10) for line in offer(n)] + FOOTER)
    assert new_lines(before, after) == ["Showing 9 of 9"] + offer(7) + offer(8) + offer(9)


def test_close_changes_are_merged_with_the_equal_lines_between_them():
    before = ["a", "b", "c", "d", "e", "f", "g", "h"]
    after = ["a", "X", "c", "d", "Y", "f", "g", "h"]
    assert new_lines(before, after) == ["X", "c", "d", "Y"]


def test_removed_lines_add_nothing():
    before = HEADER + ["We use cookies", "Accept", "Decline"] + offer(1) + FOOTER
    after = HEADER + offer(1) + FOOTER
    assert new_lines(before, after) == []


def test_page_lines_drops_blank_lines_and_spaces():
    assert page_lines("  a \n\n\t\n b") == ["a", "b"]


def test_first_changed_on_a_growing_list():
    from job_watch.web.new_content import first_changed
    before = ["menu", "offer 1", "offer 2", "Next", "footer"]
    after = ["menu", "offer 1", "offer 2", "offer 3", "offer 4", "Next", "footer"]
    assert first_changed(before, after) == 3
    assert first_changed(before, before) is None
    assert first_changed(before, ["menu", "Next", "footer"]) is None     # removals only
    assert first_changed([], after) == 0

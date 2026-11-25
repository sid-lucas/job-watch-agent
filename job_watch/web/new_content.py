"""Text that is new since the previous observation of the same page, as a pure function.

Used for "load more" lists that grow, and for pages replaced in place: only the new part
goes to the extractor, and no new part means the last click brought nothing.

The comparison is a line diff (difflib), not a set of seen lines: lines that repeat from one
offer to the next ("Geneva", "Posted 3 days ago") must stay with the new offers. Inside a
changed region, a short run of equal lines (fewer than MIN_EQUAL_RUN) is such a repeat, not
content already seen, so it is kept. Errors go toward re-sending known text, never toward
losing new text.
"""
from difflib import SequenceMatcher

MIN_EQUAL_RUN = 5       # equal lines in a row needed to count a part of the page as already seen


def page_lines(text: str) -> list[str]:
    """Non-empty lines, stripped."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def new_lines(before: list[str], after: list[str], min_equal_run: int = MIN_EQUAL_RUN) -> list[str]:
    """Lines of `after` not already present in `before`, in page order.

    Changed regions separated by fewer than `min_equal_run` equal lines are merged, with the
    equal lines between them.
    """
    regions: list[list[int]] = []       # [start, end) in `after`
    matcher = SequenceMatcher(None, before, after, autojunk=False)
    for tag, _, _, start, end in matcher.get_opcodes():
        if tag == "equal" or start == end:
            continue                    # deletions add nothing to the page
        if regions and start - regions[-1][1] < min_equal_run:
            regions[-1][1] = end
        else:
            regions.append([start, end])
    return [line for start, end in regions for line in after[start:end]]


def first_changed(before: list, after: list) -> int | None:
    """Position in `after` of the first item that is new or changed compared to `before`.

    Items are compared by value (hashable), in page order. None when `after` brings nothing
    new (same items, or only removals).
    """
    matcher = SequenceMatcher(None, before, after, autojunk=False)
    for tag, _, _, start, end in matcher.get_opcodes():
        if tag != "equal" and start < end:
            return start
    return None

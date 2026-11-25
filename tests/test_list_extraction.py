"""Offer extraction from agent observations: pure functions, no LLM, no browser."""
from job_watch.list_agent.extraction import chunks


def offer_lines(count: int) -> str:
    return "\n".join(f"Offer {n}\nGeneva\nPosted {n} days ago" for n in range(1, count + 1))


def test_short_text_is_one_chunk():
    assert chunks("Offer 1\nGeneva", max_chars=100) == ["Offer 1\nGeneva"]
    assert chunks("") == []


def test_chunks_respect_the_size_and_overlap():
    text = offer_lines(50)
    parts = chunks(text, max_chars=200, overlap_lines=3)
    assert len(parts) > 1
    assert all(len(part) <= 200 for part in parts)
    for previous, current in zip(parts, parts[1:]):
        assert current.splitlines()[:3] == previous.splitlines()[-3:]


def test_every_line_is_kept_in_order():
    text = offer_lines(50)
    parts = chunks(text, max_chars=200, overlap_lines=3)
    seen = [line for part in parts for line in part.splitlines()]
    assert set(seen) == set(text.splitlines())
    assert "Offer 50" in parts[-1]


def test_a_line_longer_than_a_chunk_is_cut():
    parts = chunks("x" * 250, max_chars=100, overlap_lines=0)
    assert [len(part) for part in parts] == [100, 100, 50]


def test_overlap_larger_than_a_chunk_still_moves_forward():
    parts = chunks(offer_lines(10), max_chars=30, overlap_lines=20)
    assert "Posted 10 days ago" in parts[-1]

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


def test_chunk_links_are_the_page_links_named_in_the_chunk():
    from job_watch.list_agent.extraction import chunk_links
    from job_watch.web.session import Element

    def link(i, name, href):
        return Element(id=i, tag="a", role="link", text=name, name=name, href=href)

    elements = [link(1, "Security Engineer", "https://jobs.example.com/offer/1"),
                link(2, "Data Analyst", "https://jobs.example.com/offer/2"),
                link(3, "Contact", "mailto:hr@example.com"),
                link(4, "", "https://jobs.example.com/empty")]
    found = chunk_links("Security  ENGINEER\nGeneva\nContact", elements)
    assert [e.id for e in found] == [1]


def test_a_link_that_joins_or_extends_the_lines_of_an_offer_belongs_to_the_chunk():
    from job_watch.list_agent.extraction import chunk_links
    from job_watch.web.session import Element
    offer = Element(id=1, tag="a", role="link", text="Security Engineer (m/w) Full-time",
                    name="Security Engineer (m/w) - REF3W", href="https://jobs.example.com/SCRT/7439")
    other = Element(id=2, tag="a", role="link", text="All jobs in Bern", name="All jobs in Bern",
                    href="https://jobs.example.com/all")
    found = chunk_links("Security Engineer (m/w)\nFull-time\nBern", [offer, other])
    assert [e.id for e in found] == [1]      # "Bern" is too short to tie a link to the chunk

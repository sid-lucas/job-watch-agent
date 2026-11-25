"""Open a job list, observe it once (no click), and extract the offers of each chunk with the LLM.

For each chunk: the answer as the LLM gave it, then what the checks in code keep.

    python -m scripts.try_extract_chunk COMPANY URL
"""
import sys

from job_watch.list_agent.extraction import check_offers, chunk_links, chunks, extract_chunk
from job_watch.web.session import BrowserSession, SessionError


def main():
    company, url = sys.argv[1], sys.argv[2]
    try:
        with BrowserSession(url) as session:
            obs = session.observe()
    except SessionError as error:
        print(f"session error: {error}")
        return
    parts = chunks(obs.new_text_full)
    print(f"{obs.title}: {len(obs.new_text_full)} chars of new text, {len(parts)} chunk(s)")
    for number, part in enumerate(parts, 1):
        answer = extract_chunk(company, part, obs.elements)
        links = len(chunk_links(part, obs.elements))
        print(f"\n--- chunk {number}: {len(part)} chars, {links} links sent")
        if answer is None:
            print("every model failed")
            continue
        print("LLM answer:")
        for offer in answer.offers:
            print(f"  {offer.title[:70]!r} | {offer.location[:30]} | {offer.reference or '-'} | {offer.link or '-'}")
        print("kept by the checks:")
        for offer in check_offers(part, answer, obs.elements, obs.url):
            status = "verified  " if offer.verified else "unverified"
            print(f"  {status} {offer.title[:70]!r} | {offer.location[:30]} | {offer.reference or '-'} | "
                  f"{offer.link or '-'}")


if __name__ == "__main__":
    main()

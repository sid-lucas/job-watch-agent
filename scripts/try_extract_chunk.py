"""Open a job list, observe it once (no click), and extract the offers of each chunk with the LLM.

The answers are printed as the LLM gave them: nothing is checked yet.

    python -m scripts.try_extract_chunk COMPANY URL
"""
import sys

from job_watch.list_agent.extraction import chunk_links, chunks, extract_chunk
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
        for offer in answer.offers:
            print(f"  {offer.title[:70]!r} | {offer.location[:30]} | {offer.reference or '-'} | {offer.link or '-'}")


if __name__ == "__main__":
    main()

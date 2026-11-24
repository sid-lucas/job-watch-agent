"""Open job lists in a BrowserSession and print one observation each (no LLM, no clicks).

    python -m scripts.try_observe URL [URL ...]
"""
import sys

from job_watch.web.session import BrowserSession, SessionError

SHOWN_ELEMENTS = 20


def main():
    for url in sys.argv[1:]:
        print(f"\n=== {url}")
        try:
            with BrowserSession(url) as session:
                obs = session.observe()
                trail = session.trail
        except SessionError as error:
            print(f"session error: {error}")
            continue
        in_forms = sum(e.in_form for e in obs.elements)
        print(f"url: {obs.url}\ntitle: {obs.title}")
        print(f"text: {len(obs.text)} chars{' (truncated)' if obs.truncated else ''}")
        print(f"elements: {len(obs.elements)}{' (truncated)' if obs.elements_truncated else ''}, "
              f"{in_forms} inside a form")
        for e in obs.elements[:SHOWN_ELEMENTS]:
            form = " [form+inputs]" if e.form_has_inputs else " [form]" if e.in_form else ""
            print(f"  [{e.id:3}] {e.role:7} {e.name[:60]!r}{form}")
        print("trail:")
        for event in trail:
            print(f"  {event.seconds:5}s {event.kind:19} {event.detail[:110]}")


if __name__ == "__main__":
    main()

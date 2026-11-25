"""Drive a BrowserSession by hand: you choose the clicks, the session applies its guardrails (no LLM).

    python -m scripts.try_click URL

Commands: "<id> p" (pagination), "<id> r" (cookie refusal), "<id> a" (cookie acceptance),
"o" (observe again), "q" (quit and print the trail).
"""
import sys

from job_watch.web.session import BrowserSession, Observation, SessionError

PURPOSES = {"p": "pagination", "r": "cookie_refusal", "a": "cookie_acceptance"}
NEW_LINES_SHOWN = 10


def show(obs: Observation, previous: Observation | None) -> None:
    print(f"\nurl: {obs.url}\ntitle: {obs.title}")
    print(f"text: {len(obs.text)} chars{' (truncated)' if obs.truncated else ''}, "
          f"elements: {len(obs.elements)}{' (truncated)' if obs.elements_truncated else ''}")
    for frame in obs.iframes:
        print(f"  iframe {'observed' if frame.observed else 'NOT observed'}: {frame.url[:100]}")
    for e in obs.elements:
        marks = [m for m, on in (("consent", e.in_consent), ("form+inputs", e.form_has_inputs),
                                 ("iframe", e.frame != "main")) if on]
        marks += [f"type={e.input_type}"] if e.input_type else []
        print(f"  [{e.id:3}] {e.role:8} {e.name[:70]!r} {' '.join(f'[{m}]' for m in marks)}")
    if previous:
        seen = set(previous.text.splitlines())
        new = [line for line in obs.text.splitlines() if line.strip() and line not in seen]
        print(f"new text lines since the previous observation: {len(new)}")
        for line in new[:NEW_LINES_SHOWN]:
            print(f"  + {line[:100]}")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        with BrowserSession(sys.argv[1]) as session:
            obs = session.observe()
            show(obs, None)
            while (command := input("\n> ").strip()) != "q":
                parts = command.split()
                if parts == ["o"]:
                    previous, obs = obs, session.observe()
                    show(obs, previous)
                elif len(parts) == 2 and parts[0].isdigit() and parts[1] in PURPOSES:
                    result = session.click(int(parts[0]), PURPOSES[parts[1]])
                    print(result.model_dump_json(indent=2))
                    if result.clicked:
                        previous, obs = obs, session.observe()
                        show(obs, previous)
                else:
                    print(__doc__)
            trail = session.trail
    except SessionError as error:
        sys.exit(f"session error: {error}")
    print("\ntrail:")
    for event in trail:
        print(f"  {event.seconds:6}s {event.kind:22} {event.detail[:110]}")


if __name__ == "__main__":
    main()

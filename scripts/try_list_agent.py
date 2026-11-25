"""Run the list agent on one job list and print every node update (navigation only, no extraction),
then a summary: LLM calls and tokens, clicks, refusals, pages reached, stop reason.

    python -m scripts.try_list_agent URL [COMPANY]
"""
import sys

from job_watch.list_agent.run import AgentRun, pages_reached, run_list_agent


def show(node: str, update: dict) -> None:
    print()
    for message in update.get("messages", []):
        if message.type == "ai":
            print(f"[{node}] asks: {[(c['name'], c['args']) for c in message.tool_calls] or message.content!r}")
        else:
            content = message.content if len(message.content) < 300 else message.content[:300] + " ..."
            print(f"[{node}] {message.name} -> {content}")
    for line in update.get("trail", []):
        print(f"[{node}] trail: {line}")
    for key in ("llm_calls", "stop_reason"):
        if key in update:
            print(f"[{node}] {key} = {update[key]}")


def summary(run: AgentRun) -> None:
    def details(*kinds):
        return [e.detail for e in run.trail if e.kind in kinds]
    tokens = run.input_tokens
    print("\n=== summary")
    print(f"stop: {run.stop}" + (f" ({run.explanation})" if run.explanation else ""))
    print(f"pages reached: {pages_reached(run.trail)}")
    print(f"llm calls: {run.llm_calls}, input tokens: total {sum(tokens)}, last call {tokens[-1] if tokens else 0}, "
          f"{run.seconds}s")
    for title, kinds in (("clicks", ("click", "cookie_accepted")), ("clicks refused", ("click_refused",)),
                         ("navigations refused", ("navigation_refused",)),
                         ("back to list", ("back_to_list", "back_to_list_refused"))):
        found = details(*kinds)
        print(f"{title} ({len(found)}):")
        for detail in found:
            print(f"  {detail[:110]}")
    print(f"new lines per observation: {[o.new_line_count for o in run.observations]}")


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    url, company = sys.argv[1], (sys.argv[2] if len(sys.argv) == 3 else "unknown")
    run = run_list_agent(url, company, on_update=show)
    summary(run)


if __name__ == "__main__":
    main()

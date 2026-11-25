"""Measure the list agent's navigation (no extraction) on the cases of evals/cases/list_agent.json.

Per case: pages reached / pages expected, whether the sample title of the furthest page was seen,
stop reason, LLM calls and input tokens, refusals. Calls the real LLM chain; no Serper credits.

    python -m evals.check_list_navigation                       # every case
    python -m evals.check_list_navigation --list watchmakers    # one company list
    python -m evals.check_list_navigation --case UBS            # one case
    python -m evals.check_list_navigation --report PATH         # also write a JSON report
"""
import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from evals.check_list_agent import ListCase, load_cases, normalise
from job_watch.list_agent.run import AgentRun, pages_reached, run_list_agent


class NavigationMetrics(BaseModel):
    company: str
    company_list: str
    pagination: str
    pages_reached: int
    pages_expected: int
    furthest_sample_page: int
    furthest_sample_seen: bool
    stop: str
    explanation: str
    llm_calls: int
    input_tokens: int
    clicks_refused: int
    navigations_refused: int
    back_to_list: int
    seconds: float
    clicks: list[str]                   # clicks done and refused, in order, for the report

    @property
    def complete(self) -> bool:
        return self.pages_reached >= self.pages_expected and self.furthest_sample_seen


def measure(case: ListCase, run: AgentRun) -> NavigationMetrics:
    seen = normalise("\n".join(o.text + "\n" + o.new_text for o in run.observations))
    furthest = max(case.sample_titles, key=lambda s: s.page)
    kinds = [e.kind for e in run.trail]
    return NavigationMetrics(
        company=case.company, company_list=case.company_list, pagination=case.pagination,
        pages_reached=pages_reached(run.trail), pages_expected=case.expected_pages,
        furthest_sample_page=furthest.page, furthest_sample_seen=normalise(furthest.title) in seen,
        stop=run.stop, explanation=run.explanation, llm_calls=run.llm_calls, input_tokens=sum(run.input_tokens),
        clicks_refused=kinds.count("click_refused"), navigations_refused=kinds.count("navigation_refused"),
        back_to_list=kinds.count("back_to_list"), seconds=run.seconds,
        clicks=[f"{e.kind}: {e.detail[:100]}" for e in run.trail
                if e.kind in ("click", "cookie_accepted", "click_refused", "back_to_list")])


def print_table(metrics: list[NavigationMetrics]) -> None:
    print(f"\n{'case':22} {'pages':>7} {'far.':>5} {'stop':32} {'llm':>4} {'tokens':>8} {'ref.':>4} {'nav.':>4} "
          f"{'back':>4} {'time':>6}")
    for m in metrics:
        far = "yes" if m.furthest_sample_seen else "NO"
        print(f"{m.company[:22]:22} {m.pages_reached:>3}/{m.pages_expected:<3} {far:>5} {m.stop[:32]:32} "
              f"{m.llm_calls:>4} {m.input_tokens:>8} {m.clicks_refused:>4} {m.navigations_refused:>4} "
              f"{m.back_to_list:>4} {m.seconds:>5.0f}s")
    for company_list in sorted({m.company_list for m in metrics}):
        group = [m for m in metrics if m.company_list == company_list]
        print(f"{company_list}: {sum(m.complete for m in group)}/{len(group)} complete, "
              f"{sum(m.llm_calls for m in group)} llm calls, {sum(m.input_tokens for m in group)} input tokens")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", choices=["banks_security", "watchmakers"])
    parser.add_argument("--case")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    cases = [c for c in load_cases()
             if (not args.list or c.company_list == args.list) and (not args.case or c.company == args.case)]
    metrics = []
    for case in cases:
        print(f"... {case.company}", flush=True)
        metrics.append(measure(case, run_list_agent(case.url, case.company)))
        m = metrics[-1]
        print(f"    pages {m.pages_reached}/{m.pages_expected}, {m.stop}, {m.llm_calls} llm calls"
              + (f" ({m.explanation})" if m.explanation else ""), flush=True)
    print_table(metrics)
    if args.report:
        args.report.write_text(json.dumps([m.model_dump() for m in metrics], indent=2, ensure_ascii=False))
        print(f"report: {args.report}")


if __name__ == "__main__":
    main()

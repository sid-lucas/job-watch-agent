"""Measure offer collection on job lists checked by hand (evals/cases/list_agent.json).

Two runners: the baseline (previous extractor on page 1 only, one LLM call per case) and the
agent (navigation by the list agent, then extraction of every observation by the code).
No Serper credits are used.

    python -m evals.check_list_agent                       # every case, baseline
    python -m evals.check_list_agent --runner agent        # every case, agent
    python -m evals.check_list_agent --list watchmakers    # one company list
    python -m evals.check_list_agent --case UBS            # one case
"""
import argparse
import json
import re
import time
import unicodedata
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from job_watch.list_agent.extraction import extract_observations
from job_watch.list_agent.run import pages_reached, run_list_agent
from job_watch.llm import call_with_retry
from job_watch.offers.extract import MAX_CHARS, ListedOffer, extract_offers
from job_watch.web.browser import render_page

CASES_FILE = Path(__file__).parent / "cases" / "list_agent.json"


# ---------- Cases (data file, validated at load time) ----------

class SampleTitle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    page: int = Field(ge=1, description="Page (or number of 'load more' clicks + 1) where the title appears")


class ListCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str = Field(min_length=1)
    company_list: Literal["banks_security", "watchmakers"]
    url: str = Field(pattern=r"^https?://")
    pagination: Literal["single", "numbered", "next_button", "load_more", "more_results"]
    expected_pages: int = Field(ge=1, description="Pages, or 'load more' clicks + 1, to read the whole list")
    expected_total: int | None = Field(default=None, ge=0)
    total_source: Literal["stated_by_page", "counted"] | None = None
    total_text: str | None = None
    checked_on: date
    sample_titles: list[SampleTitle] = Field(min_length=1, max_length=4)
    notes: str = ""

    @model_validator(mode="after")
    def check_total(self):
        if (self.expected_total is None) != (self.total_source is None):
            raise ValueError("total_source must be empty if and only if expected_total is empty")
        if (self.total_source == "stated_by_page") != (self.total_text is not None):
            raise ValueError("total_text must be set if and only if total_source is 'stated_by_page'")
        return self


class CaseFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cases: list[ListCase]


def load_cases(path: Path = CASES_FILE) -> list[ListCase]:
    return CaseFile.model_validate(json.loads(path.read_text(encoding="utf-8"))).cases


# ---------- Runners ----------

class RunResult(BaseModel):
    offers: list[ListedOffer]
    seen_text: str              # all page text seen during the run, used to check grounding
    pages_reached: int
    llm_calls: int
    stop_reason: str
    more_pages: bool | None = None
    verified: int | None = None         # agent runner: offers whose link is verified in the page
    failed_chunks: int | None = None    # agent runner: chunks for which every model failed


Runner = Callable[[ListCase], RunResult | None]


def baseline_runner(case: ListCase) -> RunResult | None:
    """Current extractor on the first page only: one render, one LLM call, no clicks."""
    page = render_page(case.url, max_chars=MAX_CHARS)
    if page is None:
        print(f"SKIP  {case.company:22} page not allowed or failed to load")
        return None
    answer = call_with_retry(extract_offers, case.company, page)
    if answer is None:
        print(f"SKIP  {case.company:22} LLM unavailable")
        return None
    return RunResult(offers=answer.offers, seen_text=page["text"], pages_reached=1, llm_calls=1,
                     stop_reason="first page only", more_pages=answer.more_pages)


def agent_runner(case: ListCase) -> RunResult | None:
    """List agent (navigation), then extraction of every observation with new text by the code."""
    run = run_list_agent(case.url, case.company)
    if not run.observations:
        print(f"SKIP  {case.company:22} {run.stop}")
        return None
    extraction = extract_observations(case.company, run.observations)
    return RunResult(
        offers=[ListedOffer(title=o.title, location=o.location, link=o.link) for o in extraction.offers],
        seen_text="\n".join(obs.new_text_full for obs in run.observations),
        pages_reached=pages_reached(run.trail),
        llm_calls=run.llm_calls + extraction.chunks,
        stop_reason=run.stop,
        verified=sum(o.verified for o in extraction.offers),
        failed_chunks=extraction.failed_chunks,
    )


RUNNERS = {"baseline": baseline_runner, "agent": agent_runner}


# ---------- Metrics ----------

# Typographic variants that an LLM may change when copying a title (no fuzzy matching beyond this)
_VARIANTS = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",   # dashes
    "‘": "'", "’": "'", "ʼ": "'", "´": "'", "`": "'",                      # apostrophes
    "∙": "·", "•": "·", "⋅": "·",                                # middle dots
})


def normalise(text: str) -> str:
    """Compare titles up to Unicode form, typographic variants, whitespace and case."""
    text = unicodedata.normalize("NFKC", text).translate(_VARIANTS)
    return re.sub(r"\s+", " ", text).strip().casefold()


class OfferRow(BaseModel):
    title: str
    location: str
    link: str
    grounded: bool                  # title found in the page text seen during the run


class CaseMetrics(BaseModel):
    company: str
    company_list: str
    found: int
    unique: int
    expected_total: int | None
    completeness: float | None      # unique offers / expected_total
    grounded: float | None          # share of titles found in the page text
    with_link: int
    samples_found: int
    samples_total: int
    samples_page1_found: int
    samples_page1_total: int
    pages_reached: int
    llm_calls: int
    stop_reason: str
    more_pages: bool | None
    verified: int | None
    failed_chunks: int | None
    seconds: float
    offers: list[OfferRow]


def measure(case: ListCase, result: RunResult, seconds: float) -> CaseMetrics:
    seen = normalise(result.seen_text)
    titles = [normalise(o.title) for o in result.offers]
    unique = len({(normalise(o.title), normalise(o.location)) for o in result.offers})
    found_titles = set(titles)
    samples = [(normalise(s.title) in found_titles, s.page) for s in case.sample_titles]
    rows = [OfferRow(title=o.title, location=o.location, link=o.link, grounded=t in seen)
            for o, t in zip(result.offers, titles)]
    return CaseMetrics(
        company=case.company,
        company_list=case.company_list,
        found=len(result.offers),
        unique=unique,
        expected_total=case.expected_total,
        completeness=unique / case.expected_total if case.expected_total else None,
        grounded=sum(r.grounded for r in rows) / len(rows) if rows else None,
        with_link=sum(1 for o in result.offers if o.link),
        samples_found=sum(ok for ok, _ in samples),
        samples_total=len(samples),
        samples_page1_found=sum(ok for ok, page in samples if page == 1),
        samples_page1_total=sum(1 for _, page in samples if page == 1),
        pages_reached=result.pages_reached,
        llm_calls=result.llm_calls,
        stop_reason=result.stop_reason,
        more_pages=result.more_pages,
        verified=result.verified,
        failed_chunks=result.failed_chunks,
        seconds=round(seconds, 1),
        offers=rows,
    )


def pct(value: float | None) -> str:
    return "  -  " if value is None else f"{value:5.0%}"


def print_case(m: CaseMetrics, verbose: bool = False) -> None:
    expected = "?" if m.expected_total is None else str(m.expected_total)
    print(f"      {m.company:22} offers {m.unique:4}/{expected:>4} ({pct(m.completeness)})  "
          f"dup {m.found - m.unique:2}  grounded {pct(m.grounded)}  links {m.with_link:4}  "
          f"samples {m.samples_found}/{m.samples_total} (p1 {m.samples_page1_found}/{m.samples_page1_total})  "
          f"pages {m.pages_reached}  llm {m.llm_calls}  more_pages {m.more_pages}  "
          + (f"verified {m.verified}/{m.unique}  failed chunks {m.failed_chunks}  " if m.verified is not None else "")
          + f"{m.seconds}s  [{m.stop_reason}]")
    if verbose:
        for row in m.offers:
            if not row.grounded:
                print(f"            not grounded: {row.title!r} | {row.location!r} | {row.link or '(no link)'}")


def print_summary(metrics: list[CaseMetrics], skipped: int) -> None:
    print()
    for company_list in sorted({m.company_list for m in metrics}):
        group = [m for m in metrics if m.company_list == company_list]
        with_total = [m for m in group if m.expected_total]
        completeness = (sum(min(m.unique, m.expected_total) for m in with_total)
                        / sum(m.expected_total for m in with_total)) if with_total else None
        grounded = [m.grounded for m in group if m.grounded is not None]
        print(f"{company_list:15} cases {len(group):2}  "
              f"completeness {pct(completeness)} (on {len(with_total)} cases with a total)  "
              f"grounded {pct(sum(grounded) / len(grounded) if grounded else None)}  "
              f"samples {sum(m.samples_found for m in group)}/{sum(m.samples_total for m in group)}  "
              f"duplicates {sum(m.found - m.unique for m in group)}  "
              f"llm calls {sum(m.llm_calls for m in group)}  {sum(m.seconds for m in group):.0f}s"
              + (f"  verified {sum(m.verified for m in group)}/{sum(m.unique for m in group)}"
                 if all(m.verified is not None for m in group) else ""))
    print(f"skipped: {skipped}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", choices=sorted(RUNNERS), default="baseline")
    parser.add_argument("--list", choices=["banks_security", "watchmakers"])
    parser.add_argument("--case", help="company name of a single case")
    parser.add_argument("--verbose", action="store_true", help="print the titles that are not grounded")
    parser.add_argument("--report", type=Path, help="write the metrics and extracted offers to this JSON file")
    args = parser.parse_args()

    cases = [c for c in load_cases()
             if (not args.list or c.company_list == args.list) and (not args.case or c.company == args.case)]
    metrics, skipped = [], 0
    for case in cases:
        start = time.perf_counter()
        result = RUNNERS[args.runner](case)
        if result is None:
            skipped += 1
            continue
        m = measure(case, result, time.perf_counter() - start)
        metrics.append(m)
        print_case(m, args.verbose)
    print_summary(metrics, skipped)
    if args.report:
        args.report.write_text(json.dumps([m.model_dump() for m in metrics], ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(f"report: {args.report}")


if __name__ == "__main__":
    main()

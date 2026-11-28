"""Check the extraction of the requirements of an ad (matching, brick 1) on public ads copied from
the database into evals/cases/requirements.json (ad text only), against an expected output.

The expected output of each case is produced once by the best model available (--freeze: the first
model of REQUIREMENTS_CHAIN that answers) and frozen in the file; it can be corrected by hand. Run the
check when the instructions change: it measures the new output against the frozen one.

    python -u -m evals.check_requirements --freeze         # cases without an expected output (1 call each)
    python -u -m evals.check_requirements                  # measure (1 call per case)
    python -u -m evals.check_requirements --model gemini:gemini-3.5-flash-lite
    python -u -m evals.check_requirements --freeze --force --case infomaniak-ai-engineer

Measures: must requirements found (recall), kind correct (on the requirements found), alternatives
grouped (an expected requirement with options found as one requirement with options), min_years
equal; extra requirements are counted, not judged.
"""
import argparse
import json
from pathlib import Path

from job_watch import config
from job_watch.llm import calls_since, model_calls
from job_watch.matching.requirements import PROMPT_ID, Requirement, extract_requirements
from job_watch.offers.ask_criteria import OfferInput
from job_watch.offers.criteria import _normal

CASES_PATH = Path(__file__).parent / "cases" / "requirements.json"


def _words(text: str) -> set[str]:
    return set(_normal(text).replace("(", " ").replace(")", " ").split())


def _closeness(expected: dict, got: Requirement) -> int:
    """2: same label; 1: overlapping quotes and a word of the label in common ("Java" and "Spring" share
    a quote but are two requirements); 0: not the same requirement."""
    if _normal(expected["label"]) == _normal(got.label):
        return 2
    a, b = _normal(expected["quote"]), _normal(got.quote)
    return int((a in b or b in a) and bool(_words(expected["label"]) & _words(got.label)))


def pair(expected: list[dict], got: list[Requirement]) -> list[tuple[dict, Requirement | None]]:
    """Each expected requirement with the closest requirement found, each found one used once."""
    pairs, used = [], set()
    for wanted in expected:
        scored = [(_closeness(wanted, g), -i, i) for i, g in enumerate(got) if i not in used]
        best = max(scored, default=(0, 0, None))
        if best[0]:
            used.add(best[2])
        pairs.append((wanted, got[best[2]] if best[0] else None))
    return pairs


class Score:
    def __init__(self):
        self.must = self.must_found = self.found = self.kind_ok = 0
        self.options = self.options_ok = self.years = self.years_ok = self.extra = 0

    def add(self, expected: list[dict], got: list[Requirement]) -> "Score":
        pairs = pair(expected, got)
        for wanted, found in pairs:
            self.must += wanted["kind"] == "must"
            self.must_found += wanted["kind"] == "must" and found is not None
            if found is None:
                continue
            self.found += 1
            self.kind_ok += wanted["kind"] == found.kind
            if wanted.get("options"):
                self.options += 1
                self.options_ok += len(found.options) >= 2
            if wanted.get("min_years") is not None:
                self.years += 1
                self.years_ok += wanted["min_years"] == found.min_years
        self.extra += len(got) - sum(found is not None for _, found in pairs)
        return self

    def merge(self, other: "Score") -> None:
        for name, value in vars(other).items():
            setattr(self, name, getattr(self, name) + value)

    def line(self) -> str:
        def part(ok, total):
            return f"{ok}/{total}" if total else "-"
        return (f"must found {part(self.must_found, self.must)}, kind {part(self.kind_ok, self.found)}, "
                f"alternatives {part(self.options_ok, self.options)}, min_years {part(self.years_ok, self.years)}, "
                f"extra {self.extra}")


def _offer(case: dict) -> OfferInput:
    return OfferInput(company=case["company"], title=case["title"], location=case["location"], ad=case["ad"])


def _chain(model: str | None) -> list:
    if not model:
        return config.REQUIREMENTS_CHAIN
    provider, _, name = model.partition(":")
    return [(provider, name, True)]


def freeze(cases: list[dict], chosen: list[dict], force: bool, chain: list) -> None:
    """Expected outputs of the chosen cases, written into the whole file after each one."""
    for case in chosen:
        if case.get("expected") and not force:
            print(f"KEEP    {case['id']}")
            continue
        extraction = extract_requirements(_offer(case), chain=chain)
        if extraction.failure:
            print(f"FAILED  {case['id']}: {extraction.failure}")
            continue
        case["expected"] = {"model": extraction.model, "prompt_id": PROMPT_ID,
                            "requirements": [r.model_dump() for r in extraction.requirements]}
        print(f"FROZEN  {case['id']}: {len(extraction.requirements)} requirements | {extraction.model}")
        CASES_PATH.write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def measure(cases: list[dict], chain: list) -> None:
    total, before = Score(), model_calls()
    for case in cases:
        expected = case.get("expected")
        if not expected:
            print(f"SKIP    {case['id']}: no expected output (--freeze)")
            continue
        extraction = extract_requirements(_offer(case), chain=chain)
        if extraction.failure:
            print(f"FAILED  {case['id']}: {extraction.failure}")
            continue
        score = Score().add(expected["requirements"], extraction.requirements)
        total.merge(score)
        print(f"{case['id'][:44]:44} {score.line()} | {extraction.model}")
        for wanted, found in pair(expected["requirements"], extraction.requirements):
            if found is None and wanted["kind"] == "must":
                print(f"      missing must: {wanted['label']}")
            elif found is not None and found.kind != wanted["kind"]:
                print(f"      kind {found.kind} instead of {wanted['kind']}: {wanted['label']}")
    stale = {c["expected"]["prompt_id"] for c in cases if c.get("expected")} - {PROMPT_ID}
    print(f"\nTotal: {total.line()}")
    if stale:
        print(f"(expected outputs frozen with other instructions: {', '.join(sorted(stale))}; now {PROMPT_ID})")
    print(f"Calls: {calls_since(before)}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--freeze", action="store_true", help="produce the missing expected outputs")
    parser.add_argument("--force", action="store_true", help="with --freeze: produce them all again")
    parser.add_argument("--model", help="provider:model instead of REQUIREMENTS_CHAIN")
    parser.add_argument("--case", action="append", help="only this case id (repeatable)")
    args = parser.parse_args(argv)
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    unknown = set(args.case or []) - {c["id"] for c in cases}
    if unknown:
        parser.error(f"unknown case(s): {', '.join(sorted(unknown))}")
    chosen = [c for c in cases if not args.case or c["id"] in args.case]
    if args.freeze:
        freeze(cases, chosen, args.force, _chain(args.model))
    else:
        measure(chosen, _chain(args.model))


if __name__ == "__main__":
    main()

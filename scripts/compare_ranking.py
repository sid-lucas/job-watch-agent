"""Score stored offers with the criteria of user_config.py and compare with their stored score (read only).

One LLM call per offer (DETAIL_CHAIN); nothing is written to the database. The raw answers of the
LLM are saved after each offer (data/criteria_answers.jsonl by default, next to the database, out of
the repository: one JSON line per offer, appended; a later line for the same offer wins) and reused
on the next run while the questions are the same: they are checked again by the code each time. A run stopped halfway resumes, and a change of points, groups, code
criteria or of the checks needs no LLM call (--no-llm).

    python -u -m scripts.compare_ranking --limit 3                  # the 3 best stored scores
    python -u -m scripts.compare_ranking --limit 3 --source career_site
    python -u -m scripts.compare_ranking --all
    python -u -m scripts.compare_ranking --all --no-llm
"""
import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from job_watch import config
from job_watch.list_agent.detail import date_stated
from job_watch.llm import calls_since, model_calls
from job_watch.offers import storage
from job_watch.offers.ask_criteria import OfferInput, answer_offer, check_offer
from job_watch.offers.criteria import Answer, CheckedAnswer, Verdict, judge
from job_watch.offers.nodes import without_board_salary

TOP = 10


def posted_date(offer: dict) -> date | None:
    """Publication date: from the feed for RSS offers; for career sites, the date of the detail fact
    sheet only when the stored page text writes it (offers stored before that check may hold an
    invented date)."""
    try:
        day = datetime.fromisoformat(offer["published"]).date() if offer["published"] else None
    except ValueError:
        return None
    if day and offer["source"] == "career_site" and not date_stated(day, offer["description"] or ""):
        return None
    return day


def offer_input(offer: dict) -> tuple[OfferInput, bool]:
    """What the LLM reads, and whether it is the full ad (career-site page; an RSS description may not be)."""
    ad = offer["description"] or ""
    if offer["source"] != "career_site":
        ad = without_board_salary(ad)       # RSS offers stored before the feed line was removed
    full_ad = offer["source"] == "career_site" and bool(ad)
    return OfferInput(company=offer["company"], title=offer["title"],
                      location=offer.get("city") or offer.get("location") or "", ad=ad), full_ad


def questions_id(asks: list[str]) -> str:
    """Short fingerprint of the questions: saved answers are reused only for the same questions."""
    return hashlib.sha256("\n".join(asks).encode()).hexdigest()[:12]


def load_saved(path: Path, questions: str) -> dict[str, tuple[list[Answer], str]]:
    """Raw answers by offer ("company|key") given to these questions, with the model that gave them;
    the last line of an offer wins."""
    saved = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry["questions"] == questions:
                answers = [Answer(id=k, answer=a, quote=q) for k, (a, q) in entry["answers"].items()]
                saved[entry["offer"]] = (answers, entry.get("model", "not recorded"))
    return saved


def save_answers(path: Path, name: str, questions: str, raw: list[Answer], model: str) -> None:
    """Append one line: only the answers that say something (a missing answer is read as unknown)."""
    answers = {a.id: [a.answer, a.quote] for a in raw if a.answer != "unknown" or a.quote}
    line = {"offer": name, "questions": questions, "model": model, "answers": answers}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(line, ensure_ascii=False) + "\n")


def answering_model(calls: dict[str, int]) -> str:
    """The model that answered, from the calls of one offer ("provider:model"; failures carry a suffix)."""
    return next((name for name in calls if " " not in name), "")


def label(offer: dict) -> str:
    return f"{offer['title'][:60]} @ {offer['company'][:25]}"


def show_top(title: str, ranked: list[tuple[dict, int, list[str]]]) -> None:
    print(f"\n=== {title} ===")
    for rank, (offer, score, reasons) in enumerate(ranked[:TOP], 1):
        print(f"{rank:2d}. {score:4d}  {label(offer)}  [{offer['source']}]")
        for reason in reasons:
            print(f"            {reason[:150]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3, help="number of offers, best stored scores first")
    parser.add_argument("--all", action="store_true", help="every stored offer, kept or rejected")
    parser.add_argument("--source", help="only this source (career_site, swissdevjobs)")
    parser.add_argument("--answers", type=Path, default=config.DB_PATH.parent / "criteria_answers.jsonl",
                        help="JSON Lines file of the raw answers, saved then reused (default: %(default)s)")
    parser.add_argument("--no-llm", action="store_true", help="only the saved answers, no LLM call")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conditions, values = [], []
    if args.source:
        conditions.append("source = ?")
        values.append(args.source)
    if not args.all:
        conditions.append("status = 'new'")
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    limit = "" if args.all else f" LIMIT {int(args.limit)}"
    rows = conn.execute(f"SELECT * FROM offers{where} ORDER BY score DESC, company, key{limit}", values).fetchall()
    conn.close()

    settings, today = config.SETTINGS, date.today()
    questions = questions_id([c.ask for c in settings.criteria])
    saved = load_saved(args.answers, questions)
    results: list[tuple[dict, Verdict, list[CheckedAnswer]]] = []
    failed, reused, models, start = [], 0, Counter(), model_calls()
    for number, row in enumerate(rows, 1):
        offer = storage.row_to_offer(row)
        name = f"{offer['company']}|{offer['key']}"
        query, full_ad = offer_input(offer)
        if name in saved:                       # same questions: same raw answers, checked again
            raw, model = saved[name]
            checked, reused = check_offer(settings, query, full_ad, raw), reused + 1
        elif args.no_llm:
            continue
        else:
            before = model_calls()
            checked, raw = answer_offer(settings, query, full_ad=full_ad)
            model = answering_model(calls_since(before)) if raw is not None else ""
            if raw is not None:                 # a failed call is not saved: the next run asks again
                save_answers(args.answers, name, questions, raw, model)
        models[model or "every model failed"] += 1
        answered = raw is not None
        if not answered:
            failed.append(offer)
        verdict = judge(settings, checked, offer["company"], posted_date(offer), today)
        results.append((offer, verdict, checked))
        print(f"[{number}/{len(rows)}] {label(offer)}: stored {offer['status']} {offer['score']} -> "
              f"{verdict.status} {verdict.score}  [{model or 'every model failed'}]", flush=True)

    # ---------- summary ----------
    old = sorted((r for r in results if r[0]["status"] == "new"), key=lambda r: -(r[0]["score"] or 0))
    new = sorted((r for r in results if r[1].status == "new"), key=lambda r: -r[1].score)
    show_top("stored ranking", [(o, o["score"] or 0, o["reasons"]) for o, _, _ in old])
    show_top("new ranking", [(o, v.score, v.reasons) for o, v, _ in new])
    old_top = {(o["company"], o["key"]) for o, _, _ in old[:TOP]}
    new_top = {(o["company"], o["key"]) for o, _, _ in new[:TOP]}
    print(f"\nIn both top {TOP}: {len(old_top & new_top)}")

    rank_old = {(o["company"], o["key"]): i for i, (o, _, _) in enumerate(old, 1)}
    rank_new = {(o["company"], o["key"]): i for i, (o, _, _) in enumerate(new, 1)}
    moves = sorted(((rank_old[k] - rank_new[k], o) for o, _, _ in new
                    if (k := (o["company"], o["key"])) in rank_old), key=lambda m: -abs(m[0]))
    print(f"\n=== biggest rank changes (kept in both; kept: {len(rank_old)} stored, {len(rank_new)} new) ===")
    for move, offer in moves[:TOP]:
        key = (offer["company"], offer["key"])
        print(f"  {rank_old[key]:3d} -> {rank_new[key]:3d}  ({move:+d})  {label(offer)}")

    print("\n=== kept before, rejected now ===")
    for offer, verdict, _ in results:
        if offer["status"] == "new" and verdict.status == "rejected":
            print(f"  {label(offer)}  (stored {offer['score']})\n      {'; '.join(verdict.reasons)[:250]}")
    print("\n=== rejected before, kept now ===")
    for offer, verdict, _ in results:
        if offer["status"] == "rejected" and verdict.status == "new":
            print(f"  {label(offer)}  -> {verdict.score}\n      was: {'; '.join(offer['reasons'])[:200]}")

    refused = [(o, a) for o, _, checked in results for a in checked
               if a.answer == "unknown" and a.quote and not a.quote_found]
    print(f"\n=== quotes not found in the ad: {len(refused)} ===")
    for offer, answer in refused[:15]:
        print(f"  {label(offer)}: {answer.ask[:50]!r} <- {answer.quote[:80]!r}")
    shown = sum(v.score >= config.MIN_SCORE for _, v, _ in new)
    print(f"\nKept: {len(rank_old)} stored, {len(rank_new)} new; new kept with score >= MIN_SCORE "
          f"({config.MIN_SCORE}): {shown}")
    print(f"Offers: {len(results)}, answers reused: {reused}, every model failed: {len(failed)}")
    print("Answers per model: " + ", ".join(f"{m} {n}" for m, n in models.most_common()))
    calls = calls_since(start)
    if calls:
        print("Calls of this run (failed, waited and skipped included): "
              + ", ".join(f"{m} {n}" for m, n in calls.items()))
    for offer in failed:
        print(f"  {label(offer)}")


if __name__ == "__main__":
    main()

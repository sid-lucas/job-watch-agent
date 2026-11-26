"""Compute rejections and scores again from the stored criteria answers, after a change of the
settings (points, groups, code criteria, kept domains) or of the checks. No LLM call.

offers: status, score and reasons from the raw answers stored with each offer, checked again.
listed_offers: kept and reject_reason from the answers on the listing data. A listed offer that
becomes kept has no detail and is not in offers (it was set aside before the detail phase): it is
reported, not fetched. Answers given to other questions are not used: those offers keep their
stored values and are counted as not rescored (they must be asked again).
"""
import json
import sqlite3

from pydantic import BaseModel

from job_watch import config
from job_watch.offers import listed, storage
from job_watch.offers.ask_criteria import OfferInput
from job_watch.offers.scoring import Asked, offer_verdict, verdict


class Change(BaseModel):
    company: str
    title: str
    before: str
    after: str


class RescoreReport(BaseModel):
    offers: int
    offer_changes: list[Change]         # status or score changed
    offers_not_rescored: int            # no answers to the current questions
    listed: int
    listed_changes: list[Change]        # kept or set aside
    listed_not_rescored: int
    kept_without_detail: list[Change]   # listed offers now kept that are not in offers


def _describe(status: str, score: int | None) -> str:
    return "rejected" if status == "rejected" else f"kept, score {score}"


def _listed_asked(row: sqlite3.Row) -> Asked | None:
    if not row["criteria_questions"]:
        return None
    answers = None if row["criteria_answers"] is None else json.loads(row["criteria_answers"])
    return Asked(criteria_questions=row["criteria_questions"], criteria_answers=answers,
                 criteria_model=row["criteria_model"] or "", full_ad=False)


def rescore(write: bool = True) -> RescoreReport:
    """Apply the current settings to every stored offer (config.DB_PATH). write=False: report only."""
    listed.connect(config.DB_PATH).close()      # listed_offers exists with all its columns, before any write
    conn = storage.connect()
    conn.row_factory = sqlite3.Row
    try:
        offer_changes, updates, offers_skipped = [], [], 0
        rows = conn.execute("SELECT * FROM offers").fetchall()
        for row in rows:
            offer = storage.row_to_offer(row)
            found = offer_verdict(offer)
            if found is None:
                offers_skipped += 1
                continue
            before, after = _describe(offer["status"], offer["score"]), _describe(found.status, found.score)
            if (offer["status"], offer["score"], offer["reasons"]) != (found.status, found.score, found.reasons):
                updates.append((found.status, found.score, json.dumps(found.reasons, ensure_ascii=False),
                                offer["company"], offer["key"]))
                if before != after:
                    offer_changes.append(Change(company=offer["company"], title=offer["title"], before=before,
                                                after=after))
        conn.executemany("UPDATE offers SET status = ?, score = ?, reasons = ? WHERE company = ? AND key = ?", updates)

        in_offers = {(row["company"], row["key"]) for row in rows}
        listed_rows = conn.execute("SELECT * FROM listed_offers WHERE kept IS NOT NULL").fetchall()
        listed_changes, kept_without_detail, listed_updates, listed_skipped = [], [], [], 0
        for row in listed_rows:
            query = OfferInput(company=row["company"], title=row["title"], location=row["location"])
            found = verdict(query, _listed_asked(row), row["domain"])
            if found is None:
                listed_skipped += 1
                continue
            rejected = found.status == "rejected"
            kept, reason = int(not rejected), "; ".join(found.reasons) if rejected else ""
            if (kept, reason) != (row["kept"], row["reject_reason"] or ""):
                listed_updates.append((kept, reason, row["company"], row["key"]))
            if kept != row["kept"]:
                change = Change(company=row["company"], title=row["title"],
                                before="kept" if row["kept"] else "set aside", after="kept" if kept else "set aside")
                listed_changes.append(change)
                if kept and (row["company"], row["key"]) not in in_offers:
                    kept_without_detail.append(change)
        conn.executemany("UPDATE listed_offers SET kept = ?, reject_reason = ? WHERE company = ? AND key = ?",
                         listed_updates)
        if write:
            conn.commit()
        else:
            conn.rollback()
    finally:
        conn.close()
    return RescoreReport(offers=len(rows), offer_changes=offer_changes, offers_not_rescored=offers_skipped,
                         listed=len(listed_rows), listed_changes=listed_changes, listed_not_rescored=listed_skipped,
                         kept_without_detail=kept_without_detail)

"""Compute rejections and scores again from the stored facts, after a change of the rules. No LLM call.

offers: status, score and reasons from all the facts of each offer. listed_offers: kept and
reject_reason from the listing facts. A listed offer that becomes kept has no detail and is not in
offers (it was set aside before the detail phase): it is reported, not fetched.
"""
import json
import sqlite3

from pydantic import BaseModel

from job_watch import config
from job_watch.list_agent.extraction import CheckedOffer
from job_watch.offers import listed, storage
from job_watch.offers.rules import facts_of, judge, listing_rejections


class Change(BaseModel):
    company: str
    title: str
    before: str
    after: str


class RescoreReport(BaseModel):
    offers: int
    offer_changes: list[Change]         # status or score changed
    listed: int
    listed_changes: list[Change]        # kept or set aside
    kept_without_detail: list[Change]   # listed offers now kept that are not in offers


def _describe(status: str, score: int | None) -> str:
    return "rejected" if status == "rejected" else f"kept, score {score}"


def rescore(write: bool = True) -> RescoreReport:
    """Apply the current rules to every stored offer (config.DB_PATH). write=False: report only."""
    listed.connect(config.DB_PATH).close()      # listed_offers exists with all its columns, before any write
    conn = storage.connect()
    conn.row_factory = sqlite3.Row
    try:
        offer_changes, updates = [], []
        rows = conn.execute("SELECT * FROM offers").fetchall()
        for row in rows:
            offer = storage.row_to_offer(row)
            verdict = judge(facts_of(offer))
            before, after = _describe(offer["status"], offer["score"]), _describe(verdict.status, verdict.score)
            if (offer["status"], offer["score"], offer["reasons"]) != (verdict.status, verdict.score, verdict.reasons):
                updates.append((verdict.status, verdict.score, json.dumps(verdict.reasons, ensure_ascii=False),
                                offer["company"], offer["key"]))
                if before != after:
                    offer_changes.append(Change(company=offer["company"], title=offer["title"], before=before,
                                                after=after))
        conn.executemany("UPDATE offers SET status = ?, score = ?, reasons = ? WHERE company = ? AND key = ?", updates)

        in_offers = {(row["company"], row["key"]) for row in rows}
        listed_rows = conn.execute("SELECT * FROM listed_offers WHERE kept IS NOT NULL").fetchall()
        listed_changes, kept_without_detail, listed_updates = [], [], []
        for row in listed_rows:
            offer = CheckedOffer(title=row["title"], location=row["location"], link=row["link"], reference="",
                                 verified=bool(row["verified"]), key=row["key"], domain=row["domain"],
                                 category=row["category"], secondary_category=row["secondary_category"])
            reasons = listing_rejections(offer, row["company"])
            kept, reason = int(not reasons), "; ".join(reasons)
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
    return RescoreReport(offers=len(rows), offer_changes=offer_changes, listed=len(listed_rows),
                         listed_changes=listed_changes, kept_without_detail=kept_without_detail)

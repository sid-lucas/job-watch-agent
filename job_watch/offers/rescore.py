"""Compute rejections and scores again from the stored criteria answers, after a change of the
settings (points, groups, code criteria, kept domains) or of the checks. No LLM call.

offers: status, score and reasons from the raw answers stored with each offer, checked again.
listed_offers: kept and reject_reason from the answers on the listing data. A listed offer that
becomes kept has no detail and is not in offers (it was set aside before the detail phase): it is
reported, not fetched. Answers given to other questions are not used: those offers keep their
stored values and are counted as not rescored, unless ask_missing is set: then they are asked
again (one LLM call each, on the stored text), their answers stored, and they are rescored.
"""
from collections.abc import Callable
import json
import sqlite3

from pydantic import BaseModel

from job_watch import config
from job_watch.offers import listed, storage
from job_watch.offers.ask_criteria import OfferInput
from job_watch.offers.scoring import Asked, ask, domain_kept, full_ad_of, offer_query, offer_verdict, verdict


class Change(BaseModel):
    company: str
    title: str
    before: str
    after: str


class RescoreReport(BaseModel):
    offers: int
    offer_changes: list[Change]         # status or score changed
    offers_not_rescored: int            # no answers to the current questions (not asked)
    offers_asked: int = 0               # asked again (ask_missing)
    listed: int
    listed_changes: list[Change]        # kept or set aside
    listed_not_rescored: int
    listed_asked: int = 0
    kept_without_detail: list[Change]   # listed offers now kept that are not in offers


def _describe(status: str, score: int | None) -> str:
    return "rejected" if status == "rejected" else f"kept, score {score}"


def _to_ask_again(offer: dict, unrecorded: bool) -> bool:
    """No answers to the current questions (domain kept); with unrecorded, also answers stored without
    the model that gave them (imported before it was recorded: they cannot be traced)."""
    if offer_verdict(offer) is None:
        return True
    return (unrecorded and bool(offer.get("criteria_questions")) and not offer.get("criteria_model")
            and domain_kept(offer.get("domain")))


def to_ask(unrecorded: bool = False) -> tuple[int, int]:
    """(offers, listed offers) that rescore(ask_missing=True) asks, one LLM call each."""
    listed.connect(config.DB_PATH).close()
    conn = storage.connect()
    conn.row_factory = sqlite3.Row
    try:
        offers = sum(_to_ask_again(storage.row_to_offer(r), unrecorded) for r in conn.execute("SELECT * FROM offers"))
        rows = conn.execute("SELECT * FROM listed_offers WHERE kept IS NOT NULL").fetchall()
        listed_rows = sum(_listed_verdict(r) is None for r in rows)
    finally:
        conn.close()
    return offers, listed_rows


def _listed_query(row: sqlite3.Row) -> OfferInput:
    return OfferInput(company=row["company"], title=row["title"], location=row["location"])


def _listed_verdict(row: sqlite3.Row):
    return verdict(_listed_query(row), listed.stored_asked(row), row["domain"])


def _answers_json(asked: Asked) -> str | None:
    answers = asked.criteria_answers
    return None if answers is None else json.dumps([a.model_dump() for a in answers], ensure_ascii=False)


def rescore(write: bool = True, ask_missing: bool = False, log: Callable[[str], None] | None = None,
            unrecorded: bool = False) -> RescoreReport:
    """Apply the current settings to every stored offer (config.DB_PATH). write=False: report only.

    ask_missing (with write): offers without answers to the current questions are asked again; each
    answer is committed at once, so a run stopped halfway keeps what was asked. An offer deferred
    (only local models left) stays not rescored. unrecorded: offers whose answers carry no model
    are asked again too.
    """
    if ask_missing and not write:
        raise ValueError("ask_missing needs write=True (asking costs LLM calls; see to_ask() for a count)")
    missing_offers, missing_listed = to_ask(unrecorded) if ask_missing else (0, 0)
    listed.connect(config.DB_PATH).close()      # listed_offers exists with all its columns, before any write
    conn = storage.connect()
    conn.row_factory = sqlite3.Row
    try:
        offer_changes, updates, offers_skipped, offers_asked = [], [], 0, 0
        rows = conn.execute("SELECT * FROM offers").fetchall()
        for row in rows:
            offer = storage.row_to_offer(row)
            found = offer_verdict(offer)
            if ask_missing and _to_ask_again(offer, unrecorded):
                asked = ask(offer_query(offer), full_ad=full_ad_of(offer), log=log,
                            progress=f"offer {offers_asked + 1}/{missing_offers}")
                offers_asked += 1
                if asked is not None:
                    conn.execute("UPDATE offers SET criteria_questions = ?, criteria_answers = ?, criteria_model = ?, "
                                 "full_ad = ? WHERE company = ? AND key = ?",
                                 (asked.criteria_questions, _answers_json(asked), asked.criteria_model,
                                  int(asked.full_ad), offer["company"], offer["key"]))
                    conn.commit()
                    offer.update(asked.model_dump())
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
        listed_changes, kept_without_detail, listed_updates, listed_skipped, listed_asked = [], [], [], 0, 0
        for row in listed_rows:
            query = _listed_query(row)
            found = _listed_verdict(row)
            if found is None and ask_missing and domain_kept(row["domain"]):
                asked = ask(query, full_ad=False, log=log, progress=f"listed {listed_asked + 1}/{missing_listed}")
                listed_asked += 1
                if asked is not None:
                    conn.execute("UPDATE listed_offers SET criteria_questions = ?, criteria_answers = ?, "
                                 "criteria_model = ? WHERE company = ? AND key = ?",
                                 (asked.criteria_questions, _answers_json(asked), asked.criteria_model,
                                  row["company"], row["key"]))
                    conn.commit()
                    found = verdict(query, asked, row["domain"])
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
                         offers_asked=offers_asked, listed=len(listed_rows), listed_changes=listed_changes,
                         listed_not_rescored=listed_skipped, listed_asked=listed_asked,
                         kept_without_detail=kept_without_detail)

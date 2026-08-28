import json
from datetime import datetime

from sqlalchemy import or_

import models


def remove_cached_possible_match(
    lost_item: models.Item,
    candidate_id: int,
    *,
    source: str | None = None,
) -> bool:
    """Remove a deleted found candidate from a lost report's saved analysis."""
    try:
        matches = json.loads(lost_item.possible_matches or "[]")
    except (TypeError, ValueError):
        matches = []

    if not isinstance(matches, list):
        matches = []

    kept_matches = []
    removed = False
    for match in matches:
        same_id = isinstance(match, dict) and str(match.get("id")) == str(candidate_id)
        same_source = source is None or (isinstance(match, dict) and match.get("source") == source)
        if same_id and same_source:
            removed = True
            continue
        kept_matches.append(match)

    if removed:
        lost_item.possible_matches = json.dumps(kept_matches) if kept_matches else None
    return removed


def _has_active_claim(db, item_id: int) -> bool:
    return db.query(models.Claim.id).filter(
        or_(
            models.Claim.lost_item_id == item_id,
            models.Claim.found_item_id == item_id,
        ),
        models.Claim.status.in_(models.ACTIVE_CLAIM_STATUSES),
    ).first() is not None


def _has_active_pending_found_link(db, lost_item_id: int, *, excluding_id: int | None = None) -> bool:
    query = db.query(models.PendingItem.id).filter(
        models.PendingItem.matched_item_id == lost_item_id,
        models.PendingItem.archived == False,
        models.PendingItem.deleted == False,
    )
    if excluding_id is not None:
        query = query.filter(models.PendingItem.id != excluding_id)
    return query.first() is not None


def release_pending_found_link(db, pending_item: models.PendingItem) -> None:
    """Release a lost report reserved by a pending found report being deleted."""
    lost_item_id = pending_item.matched_item_id
    if not lost_item_id:
        return

    lost_item = db.query(models.Item).filter(
        models.Item.id == lost_item_id,
        models.Item.status == "lost",
    ).first()
    if lost_item:
        remove_cached_possible_match(lost_item, pending_item.id, source="pending_found")
        if not _has_active_claim(db, lost_item.id) and not _has_active_pending_found_link(
            db, lost_item.id, excluding_id=pending_item.id
        ):
            lost_item.is_matched = False

    pending_item.matched_item_id = None


def release_stale_ai_match_after_reanalysis(db, lost_item: models.Item) -> int:
    """Release unverified AI links when reanalysis no longer finds a match.

    Pending claims with uploaded proof are human claim attempts and are left
    alone. Final claimed records are also untouched. Releasing the remaining
    proofless AI links restores the normal display lifecycle: found reports
    become Approved and the lost report becomes Pending.
    """
    if str(getattr(lost_item, "status", "") or "").strip().lower() != "lost":
        return 0

    released_count = 0
    released_found_ids = set()
    pending_claims = db.query(models.Claim).filter(
        models.Claim.lost_item_id == lost_item.id,
        models.Claim.status == "pending",
    ).all()
    for claim in pending_claims:
        has_submitted_proof = db.query(models.ClaimProof.id).filter(
            models.ClaimProof.claim_id == claim.id,
        ).first() is not None
        if has_submitted_proof:
            continue
        claim.status = "rejected"
        claim.admin_decision_date = datetime.utcnow()
        if claim.found_item_id is not None:
            released_found_ids.add(int(claim.found_item_id))
        released_count += 1

    pending_reservations = db.query(models.PendingItem).filter(
        models.PendingItem.matched_item_id == lost_item.id,
        models.PendingItem.archived == False,
        models.PendingItem.deleted == False,
    ).all()
    for pending_item in pending_reservations:
        pending_item.matched_item_id = None
        released_count += 1

    if released_count:
        db.flush()

    if released_found_ids:
        found_items = db.query(models.Item).filter(
            models.Item.id.in_(released_found_ids),
            models.Item.status == "found",
        ).all()
        for found_item in found_items:
            found_item.is_matched = _has_active_claim(db, found_item.id)

    lost_item.is_matched = bool(
        _has_active_claim(db, lost_item.id)
        or _has_active_pending_found_link(db, lost_item.id)
    )
    return released_count


def delete_item_claims_and_release_matches(db, item: models.Item) -> None:
    """Delete an item's claims and make no-longer-linked counterparts matchable."""
    linked_claims = db.query(models.Claim).filter(
        or_(
            models.Claim.lost_item_id == item.id,
            models.Claim.found_item_id == item.id,
        )
    ).all()

    counterpart_ids = {
        claim.found_item_id if item.status == "lost" else claim.lost_item_id
        for claim in linked_claims
        if (claim.found_item_id if item.status == "lost" else claim.lost_item_id) is not None
    }
    counterparts = (
        db.query(models.Item).filter(models.Item.id.in_(counterpart_ids)).all()
        if counterpart_ids
        else []
    )

    if linked_claims:
        claim_ids = [claim.id for claim in linked_claims]
        db.query(models.ClaimDecisionReport).filter(
            models.ClaimDecisionReport.claim_id.in_(claim_ids)
        ).delete(synchronize_session=False)
        db.query(models.ClaimProof).filter(
            models.ClaimProof.claim_id.in_(claim_ids)
        ).delete(synchronize_session=False)
        db.query(models.Claim).filter(
            models.Claim.id.in_(claim_ids)
        ).delete(synchronize_session=False)
        db.flush()

    for counterpart in counterparts:
        if item.status == "found" and counterpart.status == "lost":
            remove_cached_possible_match(counterpart, item.id, source="found")

        has_pending_reservation = (
            counterpart.status == "lost"
            and _has_active_pending_found_link(db, counterpart.id)
        )
        if not _has_active_claim(db, counterpart.id) and not has_pending_reservation:
            counterpart.is_matched = False

    item.is_matched = False

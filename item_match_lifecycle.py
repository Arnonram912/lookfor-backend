import json
from datetime import datetime

from sqlalchemy import or_, text

import models
from matching_metrics import is_automatic_match_candidate


def _stored_match_score(value) -> float | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.endswith("%"):
        try:
            return max(0.0, min(1.0, float(text[:-1].strip()) / 100.0))
        except ValueError:
            return None
    try:
        return max(0.0, min(1.0, float(text)))
    except ValueError:
        return None


def _is_replaceable_ai_claim(claim) -> bool:
    label = str(getattr(claim, "similarity_score", "") or "").strip().lower()
    return label == "auto match" or _stored_match_score(label) is not None


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


def replace_weaker_ai_match_after_reanalysis(
    db,
    lost_item: models.Item,
    strongest_match: dict | None,
    *,
    ranked_candidates: list[dict] | None = None,
    previous_matches: list[dict] | None = None,
) -> int:
    """Release a proofless AI link only when a different candidate scores higher.

    Final claims, manual claims, and pending claims with submitted proof are
    protected. The caller can then create the new highest-scoring link in the
    same transaction.
    """
    if not strongest_match or str(getattr(lost_item, "status", "") or "").lower() != "lost":
        return 0

    new_id = strongest_match.get("id")
    new_source = strongest_match.get("source", "found")
    new_score = _stored_match_score(strongest_match.get("score"))
    if new_id is None or new_score is None:
        return 0

    protected_claim = db.query(models.Claim.id).filter(
        models.Claim.lost_item_id == lost_item.id,
        models.Claim.status.in_(models.CLAIMED_CLAIM_STATUSES),
    ).first()
    if protected_claim:
        return 0

    pending_claims = db.query(models.Claim).filter(
        models.Claim.lost_item_id == lost_item.id,
        models.Claim.status == "pending",
    ).all()
    reservations = db.query(models.PendingItem).filter(
        models.PendingItem.matched_item_id == lost_item.id,
        models.PendingItem.archived == False,
        models.PendingItem.deleted == False,
    ).all()
    if not pending_claims and not reservations:
        return 0

    current_links = [
        ("found", int(claim.found_item_id), claim)
        for claim in pending_claims
        if claim.found_item_id is not None
    ] + [
        ("pending_found", int(item.id), item)
        for item in reservations
    ]
    already_linked = any(
        source == new_source and item_id == int(new_id)
        for source, item_id, _ in current_links
    )

    if already_linked:
        # A previous buggy lifecycle could leave two proofless AI links active.
        # Keeping the strongest pair must also retire every weaker duplicate;
        # returning early here was the reason two found reports stayed marked.
        for source, item_id, link in current_links:
            if source == new_source and item_id == int(new_id):
                continue
            if source == "found":
                if not _is_replaceable_ai_claim(link):
                    return 0
                has_proof = db.query(models.ClaimProof.id).filter(
                    models.ClaimProof.claim_id == link.id,
                ).first() is not None
                if has_proof:
                    return 0

        released_found_ids = set()
        released_count = 0
        for source, item_id, link in current_links:
            if source == new_source and item_id == int(new_id):
                continue
            if source == "found":
                link.status = "rejected"
                link.admin_decision_date = datetime.utcnow()
                released_found_ids.add(item_id)
            else:
                link.matched_item_id = None
            released_count += 1

        if released_count:
            db.flush()
            if released_found_ids:
                released_found_items = db.query(models.Item).filter(
                    models.Item.id.in_(released_found_ids),
                    models.Item.status == "found",
                ).all()
                for found_item in released_found_items:
                    found_item.is_matched = _has_active_claim(db, found_item.id)
            lost_item.is_matched = True
        return released_count

    for claim in pending_claims:
        if not _is_replaceable_ai_claim(claim):
            return 0
        has_proof = db.query(models.ClaimProof.id).filter(
            models.ClaimProof.claim_id == claim.id,
        ).first() is not None
        if has_proof:
            return 0

    candidate_scores = {}
    for candidate in [*(previous_matches or []), *(ranked_candidates or [])]:
        if not isinstance(candidate, dict) or candidate.get("id") is None:
            continue
        score = _stored_match_score(candidate.get("score"))
        if score is not None:
            candidate_scores[(candidate.get("source", "found"), int(candidate["id"]))] = score

    old_scores = []
    for source, item_id, link in current_links:
        score = candidate_scores.get((source, item_id))
        if score is None and source == "found":
            score = _stored_match_score(getattr(link, "similarity_score", None))
        if score is None:
            # A replacement must be demonstrably stronger, never assumed so.
            return 0
        old_scores.append(score)

    if not old_scores or new_score <= max(old_scores):
        return 0
    return release_stale_ai_match_after_reanalysis(db, lost_item)


def strongest_upload_match(match_result: dict | None) -> dict | None:
    """Return the one threshold-qualified candidate an upload may try to link.

    A newly uploaded found item still needs to see a lost item that is currently
    reserved by a weaker AI match. The scorer correctly marks that lost item as
    unavailable for an ordinary second link, so we ignore only that availability
    flag here. ``authorize_single_ai_link`` performs the ownership/replacement
    check before anything is actually linked.
    """
    if not isinstance(match_result, dict):
        return None

    candidate = match_result.get("matched_item")
    if not isinstance(candidate, dict):
        ranked = match_result.get("ranked_candidates")
        candidate = ranked[0] if isinstance(ranked, list) and ranked else None
    if not isinstance(candidate, dict):
        return None

    candidate = {**candidate, "available_for_match": True}
    return candidate if is_automatic_match_candidate(candidate) else None


def authorize_single_ai_link(
    db,
    lost_item: models.Item,
    new_match: dict | None,
    *,
    ranked_candidates: list[dict] | None = None,
) -> tuple[bool, int]:
    """Authorize one AI link, replacing a strictly weaker AI link if safe.

    Returns ``(authorized, released_link_count)``. Human-reviewed/final claims,
    manual pending claims, and pending claims with proof are never replaced.
    """
    if not new_match or str(getattr(lost_item, "status", "") or "").lower() != "lost":
        return False, 0

    # Serialize competing uploads for the same lost report. SQL Server does not
    # emit a row lock for SQLAlchemy's generic ``with_for_update()``, so use its
    # explicit update/range-lock hints there. Lightweight unit-test sessions do
    # not expose a bind and intentionally skip this database-only guard.
    try:
        dialect_name = db.get_bind().dialect.name
    except (AttributeError, TypeError):
        dialect_name = None
    if dialect_name == "mssql":
        db.execute(
            text("SELECT id FROM items WITH (UPDLOCK, HOLDLOCK) WHERE id = :lost_item_id"),
            {"lost_item_id": lost_item.id},
        ).first()
    elif dialect_name and dialect_name != "sqlite":
        db.query(models.Item.id).filter(
            models.Item.id == lost_item.id
        ).with_for_update().first()

    active_claims = db.query(models.Claim).filter(
        models.Claim.lost_item_id == lost_item.id,
        models.Claim.status.in_(models.ACTIVE_CLAIM_STATUSES),
    ).all()
    reservations = db.query(models.PendingItem).filter(
        models.PendingItem.matched_item_id == lost_item.id,
        models.PendingItem.archived == False,
        models.PendingItem.deleted == False,
    ).all()

    new_source = new_match.get("source", "found")
    new_id = new_match.get("id")
    already_linked = any(
        new_source == "found" and claim.found_item_id == new_id
        for claim in active_claims
    ) or any(
        new_source == "pending_found" and pending.id == new_id
        for pending in reservations
    )
    if already_linked:
        return True, 0

    if not active_claims and not reservations:
        # Repair a stale display flag while establishing the authoritative link.
        lost_item.is_matched = False
        return True, 0

    try:
        cached_matches = json.loads(getattr(lost_item, "possible_matches", None) or "[]")
        cached_matches = cached_matches if isinstance(cached_matches, list) else []
    except (TypeError, ValueError):
        cached_matches = []

    released = replace_weaker_ai_match_after_reanalysis(
        db,
        lost_item,
        new_match,
        ranked_candidates=ranked_candidates or cached_matches,
        previous_matches=cached_matches,
    )
    return released > 0, released


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

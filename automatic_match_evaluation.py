import json
import re
from collections.abc import Iterable
from typing import Any

import models
from matching_metrics import (
    MATCH_THRESHOLD,
    clamp_similarity_score,
    evaluate_match_dataset,
    evaluate_ranking_metrics,
)


def parse_claim_similarity(value: Any) -> float | None:
    """Parse persisted claim confidence values while excluding manual matches."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        percent_match = re.search(r"(-?\d+(?:\.\d+)?)\s*%", text)
        if percent_match:
            numeric = float(percent_match.group(1)) / 100.0
        else:
            try:
                numeric = float(text)
            except ValueError:
                return None
    if numeric > 1:
        numeric /= 100.0
    return round(clamp_similarity_score(numeric), 4)


def _saved_candidates(lost_item: Any) -> list[dict]:
    try:
        candidates = json.loads(getattr(lost_item, "possible_matches", None) or "[]")
    except (TypeError, ValueError):
        return []
    return candidates if isinstance(candidates, list) else []


def calculate_automatic_match_evaluation(
    claims: Iterable[Any],
    lost_items: Iterable[Any],
) -> dict[str, int | float | str]:
    """Calculate live metrics from scored claim decisions and saved rankings."""
    decided_claims = []
    classification_records = []
    approved_found_by_lost: dict[int, int] = {}

    for claim in claims:
        status = str(getattr(claim, "status", "") or "").strip().lower()
        if status not in {*models.CLAIMED_CLAIM_STATUSES, "rejected"}:
            continue
        decided_claims.append(claim)
        is_actual_match = status in models.CLAIMED_CLAIM_STATUSES
        if is_actual_match and claim.lost_item_id is not None and claim.found_item_id is not None:
            approved_found_by_lost[int(claim.lost_item_id)] = int(claim.found_item_id)

        score = parse_claim_similarity(getattr(claim, "similarity_score", None))
        if score is not None:
            classification_records.append({
                "actual_match": is_actual_match,
                "score": score,
            })

    metrics = evaluate_match_dataset(classification_records, threshold=MATCH_THRESHOLD)

    ranking_records = []
    for lost_item in lost_items:
        lost_id = int(getattr(lost_item, "id"))
        approved_found_id = approved_found_by_lost.get(lost_id)
        if approved_found_id is None:
            continue
        seen_candidate_ids = set()
        for candidate in _saved_candidates(lost_item):
            if not isinstance(candidate, dict) or candidate.get("source", "found") != "found":
                continue
            try:
                candidate_id = int(candidate.get("id"))
                score = float(candidate.get("raw_score", candidate.get("score", 0)) or 0)
            except (TypeError, ValueError):
                continue
            if candidate_id in seen_candidate_ids:
                continue
            seen_candidate_ids.add(candidate_id)
            ranking_records.append({
                "query_id": str(lost_id),
                "actual_match": candidate_id == approved_found_id,
                "score": clamp_similarity_score(score),
            })

    for cutoff in (1, 5, 10):
        metrics.update(evaluate_ranking_metrics(ranking_records, k=cutoff))

    metrics.update({
        "source": "admin_decided_claims",
        "decided_claims": len(decided_claims),
        "scored_decisions": len(classification_records),
        "unscored_decisions": len(decided_claims) - len(classification_records),
        "ranked_candidates": len(ranking_records),
        "approved_ranking_queries": len(approved_found_by_lost),
    })
    return metrics

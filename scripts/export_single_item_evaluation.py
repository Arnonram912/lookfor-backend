"""Export one lost report's production match evaluation to CSV without DB writes."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from database import SessionLocal
import models
from main import actively_linked_found_candidate_ids, compute_text_detail_matches, get_text_embedding
from matching_metrics import is_automatic_match_candidate


FIELDS = [
    "query_lost_id", "query_item_name", "query_category", "query_location",
    "candidate_id", "candidate_source", "candidate_item_name", "candidate_category",
    "candidate_location", "rank", "raw_score", "final_score", "competition_decay",
    "image_similarity", "text_similarity", "detail_similarity", "category_similarity",
    "item_type_similarity", "location_similarity", "brand_similarity", "color_similarity",
    "description_similarity", "event_time_similarity", "available_for_match",
    "is_already_matched", "is_linked_to_query", "linked_lost_id", "automatic_eligible",
    "selected_automatic_match", "item_type_conflict", "brand_conflict", "color_conflict",
    "confirmed_color_conflict", "color_review_required", "visual_type_conflict",
    "visual_type_review_required", "warning",
]


def export_evaluation(lost_item_id: int, output_path: Path) -> dict:
    db = SessionLocal()
    try:
        item = db.query(models.Item).filter(
            models.Item.id == lost_item_id,
            models.Item.status.ilike("lost"),
        ).first()
        if not item:
            raise ValueError(f"Lost item {lost_item_id} was not found.")

        query_parts = [
            f"A {item.color}" if item.color else "An item",
            item.brand or "",
            item.category or "",
        ]
        query_text = (
            f"{' '.join(part for part in query_parts if part)} "
            f"at {item.location or 'Unknown'}. {(item.description or '').strip()}"
        ).strip()
        query_text_vec = get_text_embedding(query_text)

        image_vec = None
        if item.image_embedding:
            try:
                parsed_image_vec = np.array(json.loads(item.image_embedding)).flatten()
                image_vec = parsed_image_vec if parsed_image_vec.size else None
            except (TypeError, ValueError):
                image_vec = None

        result = compute_text_detail_matches(
            db,
            category=item.category,
            location=item.location or "Unknown",
            description=item.description,
            brand=item.brand,
            color=item.color,
            status=item.status,
            search_vec=image_vec,
            query_text_vec=query_text_vec,
            item_name=item.item_name,
            date_value=item.date,
            time_found=item.time_found,
            exclude_item_id=item.id,
            include_candidate_ids=actively_linked_found_candidate_ids(db, item.id),
            current_lost_item_id=item.id,
            include_observation_candidates=True,
        )
        candidates = result.get("_observation_candidates", [])

        active_claims = db.query(models.Claim).filter(
            models.Claim.status.in_(models.ACTIVE_CLAIM_STATUSES),
        ).all()
        found_claim_owner = {
            int(claim.found_item_id): int(claim.lost_item_id)
            for claim in active_claims
            if claim.found_item_id is not None and claim.lost_item_id is not None
        }
        pending_owner = {
            int(pending.id): (
                int(pending.matched_item_id) if pending.matched_item_id is not None else None
            )
            for pending in db.query(models.PendingItem).filter(
                models.PendingItem.archived == False,
                models.PendingItem.deleted == False,
            ).all()
        }

        automatic = result.get("matched_item") or {}
        automatic_key = (automatic.get("source", "found"), automatic.get("id"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=FIELDS)
            writer.writeheader()
            for candidate in candidates:
                source = candidate.get("source", "found")
                candidate_id = int(candidate["id"])
                linked_lost_id = (
                    pending_owner.get(candidate_id)
                    if source == "pending_found"
                    else found_claim_owner.get(candidate_id)
                )
                writer.writerow({
                    "query_lost_id": item.id,
                    "query_item_name": item.item_name,
                    "query_category": item.category,
                    "query_location": item.location,
                    "candidate_id": candidate_id,
                    "candidate_source": source,
                    "candidate_item_name": candidate.get("item_name"),
                    "candidate_category": candidate.get("category"),
                    "candidate_location": candidate.get("location"),
                    "rank": candidate.get("rank"),
                    "raw_score": candidate.get("raw_score"),
                    "final_score": candidate.get("score"),
                    "competition_decay": candidate.get("competition_decay"),
                    "image_similarity": candidate.get("image_similarity"),
                    "text_similarity": candidate.get("text_similarity"),
                    "detail_similarity": candidate.get("detail_similarity"),
                    "category_similarity": candidate.get("category_similarity"),
                    "item_type_similarity": candidate.get("item_type_similarity"),
                    "location_similarity": candidate.get("location_similarity"),
                    "brand_similarity": candidate.get("brand_similarity"),
                    "color_similarity": candidate.get("color_similarity"),
                    "description_similarity": candidate.get("description_similarity"),
                    "event_time_similarity": candidate.get("event_time_similarity"),
                    "available_for_match": candidate.get("available_for_match"),
                    "is_already_matched": candidate.get("is_already_matched"),
                    "is_linked_to_query": linked_lost_id == item.id,
                    "linked_lost_id": linked_lost_id,
                    "automatic_eligible": is_automatic_match_candidate(candidate),
                    "selected_automatic_match": automatic_key == (source, candidate_id),
                    "item_type_conflict": candidate.get("item_type_conflict"),
                    "brand_conflict": candidate.get("brand_conflict"),
                    "color_conflict": candidate.get("color_conflict"),
                    "confirmed_color_conflict": candidate.get("confirmed_color_conflict"),
                    "color_review_required": candidate.get("color_review_required"),
                    "visual_type_conflict": candidate.get("visual_type_conflict"),
                    "visual_type_review_required": candidate.get("visual_type_review_required"),
                    "warning": candidate.get("warning"),
                })

        return {
            "output": str(output_path.resolve()),
            "query_id": item.id,
            "query_name": item.item_name,
            "candidate_rows": len(candidates),
            "highest_score": result.get("highest_score"),
            "highest_raw_score": result.get("highest_raw_score"),
            "automatic_match_id": automatic.get("id"),
            "automatic_match_source": automatic.get("source"),
        }
    finally:
        db.rollback()
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("lost_item_id", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(export_evaluation(args.lost_item_id, args.output), indent=2))


if __name__ == "__main__":
    main()

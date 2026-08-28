"""Automatic evaluation of LookFor against a fixed, labeled benchmark dataset."""

from __future__ import annotations

import csv
import json
import math
import os
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from matching_metrics import (
    MATCH_THRESHOLD,
    POSSIBLE_MATCH_THRESHOLD,
    calculate_match_score,
    clamp_similarity_score,
    evaluate_match_dataset,
    evaluate_ranking_metrics,
    is_automatic_match_candidate,
)


TRUE_VALUES = {"1", "true", "yes", "y"}
FALSE_VALUES = {"0", "false", "no", "n"}
DEFAULT_DATASET_PATH = Path(__file__).resolve().with_name("matching_dataset.csv")
DEFAULT_MINIMUM_RECORDS = 20
DEFAULT_MINIMUM_QUERIES = 5


def parse_label(value: Any, row_number: int) -> bool:
    normalized = str(value or "").strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(
        f"Row {row_number}: actual_match must be true/false, yes/no, or 1/0."
    )


def _parse_similarity(value: Any, row_number: int, column: str) -> float:
    try:
        similarity = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Row {row_number}: {column} must be numeric.") from exc
    if not math.isfinite(similarity) or not 0 <= similarity <= 1:
        raise ValueError(f"Row {row_number}: {column} must be between 0 and 1.")
    return similarity


def load_labeled_dataset(path: Path) -> list[dict[str, object]]:
    """Load verified labels and score each pair with the production score formula."""
    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"query_id", "actual_match", "image_similarity", "text_similarity"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required CSV columns: {', '.join(sorted(missing))}")

        for row_number, row in enumerate(reader, start=2):
            query_id = str(row.get("query_id") or "").strip()
            if not query_id:
                raise ValueError(f"Row {row_number}: query_id cannot be empty.")
            actual_match_value = str(row.get("actual_match") or "").strip()
            image_similarity = _parse_similarity(
                row.get("image_similarity"), row_number, "image_similarity"
            )
            text_similarity = _parse_similarity(
                row.get("text_similarity"), row_number, "text_similarity"
            )
            supplied_score = str(row.get("score") or "").strip()
            score = (
                _parse_similarity(supplied_score, row_number, "score")
                if supplied_score
                else calculate_match_score(image_similarity, text_similarity)
            )
            records.append(
                {
                    "query_id": query_id,
                    "actual_match": parse_label(actual_match_value, row_number),
                    "score": score,
                }
            )
    return records


def _positive_int(value: Any, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def configured_dataset_path() -> Path:
    configured = str(os.getenv("MATCHING_EVALUATION_DATASET", "") or "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_DATASET_PATH


def _empty_metrics() -> dict[str, int | float]:
    metrics = evaluate_match_dataset([], threshold=MATCH_THRESHOLD)
    for cutoff in (1, 5, 10):
        metrics.update(evaluate_ranking_metrics([], k=cutoff))
    return metrics


def calculate_labeled_dataset_evaluation(
    path: Path | str | None = None,
    *,
    minimum_records: int | None = None,
    minimum_queries: int | None = None,
) -> dict[str, Any]:
    """Calculate reproducible metrics without using live administrator decisions."""
    dataset_path = Path(path) if path is not None else configured_dataset_path()
    required_records = _positive_int(
        minimum_records
        if minimum_records is not None
        else os.getenv("MATCHING_EVALUATION_MIN_RECORDS"),
        DEFAULT_MINIMUM_RECORDS,
    )
    required_queries = _positive_int(
        minimum_queries
        if minimum_queries is not None
        else os.getenv("MATCHING_EVALUATION_MIN_QUERIES"),
        DEFAULT_MINIMUM_QUERIES,
    )
    result: dict[str, Any] = {
        **_empty_metrics(),
        "source": "fixed_labeled_dataset",
        "dataset_name": dataset_path.name,
        "dataset_status": "missing",
        "dataset_error": None,
        "labeled_records": 0,
        "positive_records": 0,
        "negative_records": 0,
        "query_count": 0,
        "minimum_records": required_records,
        "minimum_queries": required_queries,
        "is_sufficient": False,
        "dataset_modified_at": None,
    }
    if not dataset_path.is_file():
        return result

    try:
        records = load_labeled_dataset(dataset_path)
    except (OSError, ValueError) as exc:
        result["dataset_status"] = "invalid"
        result["dataset_error"] = str(exc)
        return result

    metrics = evaluate_match_dataset(records, threshold=MATCH_THRESHOLD)
    for cutoff in (1, 5, 10):
        metrics.update(evaluate_ranking_metrics(records, k=cutoff))

    positive_records = sum(1 for record in records if record["actual_match"])
    negative_records = len(records) - positive_records
    query_count = len({str(record["query_id"]) for record in records})
    is_sufficient = (
        len(records) >= required_records
        and query_count >= required_queries
        and positive_records > 0
        and negative_records > 0
    )
    result.update(metrics)
    result.update(
        {
            "dataset_status": "ready" if is_sufficient else "insufficient_data",
            "labeled_records": len(records),
            "positive_records": positive_records,
            "negative_records": negative_records,
            "query_count": query_count,
            "is_sufficient": is_sufficient,
            "dataset_modified_at": datetime.fromtimestamp(
                dataset_path.stat().st_mtime, timezone.utc
            ).isoformat(),
        }
    )
    return result


def calculate_live_matching_analytics(lost_items: Iterable[Any]) -> dict[str, Any]:
    """Summarize saved CLIP rankings without treating predictions as truth labels."""
    items = list(lost_items)
    reports_with_candidates = 0
    matched_reports = 0
    invalid_caches = 0
    saved_candidates = 0
    threshold_candidates = 0
    pending_candidates = 0
    decayed_candidates = 0
    visual_type_conflicts = 0
    automatic_ready_reports = 0
    top_confidences: list[float] = []
    top_image_similarities: list[float] = []
    top_text_similarities: list[float] = []
    top_detail_similarities: list[float] = []

    def append_component(candidate: dict[str, Any], key: str, values: list[float]) -> None:
        raw_value = candidate.get(key)
        if raw_value is None or isinstance(raw_value, bool):
            return
        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError):
            return
        if math.isfinite(numeric_value):
            values.append(clamp_similarity_score(numeric_value))

    def average(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    for item in items:
        if bool(getattr(item, "is_matched", False)):
            matched_reports += 1
        serialized = getattr(item, "possible_matches", None)
        if not serialized:
            continue
        try:
            candidates = json.loads(serialized)
        except (TypeError, ValueError, json.JSONDecodeError):
            invalid_caches += 1
            continue
        if not isinstance(candidates, list):
            invalid_caches += 1
            continue
        candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
        if not candidates:
            continue

        reports_with_candidates += 1
        saved_candidates += len(candidates)
        first_candidate = candidates[0]
        top_confidences.append(clamp_similarity_score(first_candidate.get("score")))
        append_component(first_candidate, "image_similarity", top_image_similarities)
        append_component(first_candidate, "text_similarity", top_text_similarities)
        append_component(first_candidate, "detail_similarity", top_detail_similarities)
        if is_automatic_match_candidate(first_candidate):
            automatic_ready_reports += 1

        for candidate in candidates:
            raw_score = clamp_similarity_score(
                candidate.get("raw_score", candidate.get("score"))
            )
            if raw_score >= MATCH_THRESHOLD:
                threshold_candidates += 1
            if str(candidate.get("source", "found")) == "pending_found":
                pending_candidates += 1
            if clamp_similarity_score(candidate.get("competition_decay")) > 0:
                decayed_candidates += 1
            if bool(candidate.get("visual_type_conflict")):
                visual_type_conflicts += 1

    return {
        "source": "saved_live_clip_rankings",
        "active_lost_reports": len(items),
        "reports_with_candidates": reports_with_candidates,
        "reports_without_candidates": len(items) - reports_with_candidates,
        "matched_lost_reports": matched_reports,
        "saved_candidates": saved_candidates,
        "possible_threshold": POSSIBLE_MATCH_THRESHOLD,
        "match_threshold": MATCH_THRESHOLD,
        "threshold_candidates": threshold_candidates,
        "pending_found_candidates": pending_candidates,
        "decayed_candidates": decayed_candidates,
        "visual_type_conflicts": visual_type_conflicts,
        "automatic_ready_reports": automatic_ready_reports,
        "average_top_confidence": average(top_confidences),
        "average_top_image_similarity": average(top_image_similarities),
        "average_top_text_similarity": average(top_text_similarities),
        "average_top_detail_similarity": average(top_detail_similarities),
        "top_image_samples": len(top_image_similarities),
        "top_text_samples": len(top_text_similarities),
        "top_detail_samples": len(top_detail_similarities),
        "invalid_caches": invalid_caches,
    }

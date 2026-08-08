"""Shared LookFor match scoring and dataset-level evaluation metrics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from collections import defaultdict
from typing import Any


IMAGE_WEIGHT = 0.60
TEXT_WEIGHT = 0.40

POSSIBLE_MATCH_THRESHOLD = 0.45
MATCH_THRESHOLD = 0.55


def calculate_match_score(
    image_similarity: float,
    text_similarity: float,
) -> float:
    """Calculate the canonical image-text score used by every match flow."""
    score = (float(image_similarity) * IMAGE_WEIGHT) + (
        float(text_similarity) * TEXT_WEIGHT
    )
    return round(max(0.0, min(1.0, score)), 4)


def is_match(score: float, threshold: float = MATCH_THRESHOLD) -> bool:
    return float(score) >= float(threshold)


def _actual_match(record: Mapping[str, Any], index: int) -> bool:
    if "actual_match" not in record:
        raise ValueError(f"Record {index} must contain 'actual_match'.")
    actual_raw = record["actual_match"]
    if isinstance(actual_raw, bool):
        return actual_raw
    if actual_raw in (0, 1):
        return bool(actual_raw)
    raise ValueError(f"Record {index} actual_match must be boolean or 0/1.")


def evaluate_match_dataset(
    records: Iterable[Mapping[str, Any]],
    threshold: float = MATCH_THRESHOLD,
) -> dict[str, int | float]:
    """Evaluate records containing a numeric ``score`` and labeled ``actual_match``."""
    true_positive = false_positive = true_negative = false_negative = 0

    for index, record in enumerate(records, start=1):
        if "score" not in record:
            raise ValueError(f"Record {index} must contain 'score'.")
        actual = _actual_match(record, index)

        try:
            predicted = is_match(float(record["score"]), threshold)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Record {index} score must be numeric.") from exc

        if actual and predicted:
            true_positive += 1
        elif not actual and predicted:
            false_positive += 1
        elif actual and not predicted:
            false_negative += 1
        else:
            true_negative += 1

    total = true_positive + false_positive + true_negative + false_negative
    accuracy = (true_positive + true_negative) / total if total else 0.0
    precision_denominator = true_positive + false_positive
    precision = true_positive / precision_denominator if precision_denominator else 0.0
    recall_denominator = true_positive + false_negative
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    f1_denominator = precision + recall
    f1_score = 2 * precision * recall / f1_denominator if f1_denominator else 0.0

    return {
        "threshold": float(threshold),
        "total": total,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "true_negative": true_negative,
        "false_negative": false_negative,
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1_score, 4),
    }


def evaluate_ranking_metrics(
    records: Iterable[Mapping[str, Any]],
    k: int = 5,
) -> dict[str, int | float]:
    """Calculate macro Recall@K and MRR for candidates grouped by query_id.

    Queries without a relevant candidate cannot measure retrieval quality and are
    reported separately rather than included in either metric.
    """
    if k < 1:
        raise ValueError("k must be at least 1.")

    grouped: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for index, record in enumerate(records, start=1):
        query_id = str(record.get("query_id", "") or "").strip()
        if not query_id:
            raise ValueError(f"Record {index} must contain a non-empty 'query_id'.")
        if "score" not in record:
            raise ValueError(f"Record {index} must contain 'score'.")
        try:
            score = float(record["score"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Record {index} score must be numeric.") from exc
        grouped[query_id].append((score, _actual_match(record, index)))

    recall_values: list[float] = []
    reciprocal_ranks: list[float] = []
    queries_without_relevant = 0

    for candidates in grouped.values():
        ranked = sorted(candidates, key=lambda candidate: candidate[0], reverse=True)
        relevant_total = sum(1 for _, actual in ranked if actual)
        if relevant_total == 0:
            queries_without_relevant += 1
            continue

        relevant_in_top_k = sum(1 for _, actual in ranked[:k] if actual)
        recall_values.append(relevant_in_top_k / relevant_total)
        first_relevant_rank = next(
            rank for rank, (_, actual) in enumerate(ranked, start=1) if actual
        )
        reciprocal_ranks.append(1 / first_relevant_rank)

    evaluated_queries = len(recall_values)
    recall_at_k = sum(recall_values) / evaluated_queries if evaluated_queries else 0.0
    mrr = sum(reciprocal_ranks) / evaluated_queries if evaluated_queries else 0.0

    return {
        "ranking_queries": len(grouped),
        "ranking_queries_evaluated": evaluated_queries,
        "queries_without_relevant": queries_without_relevant,
        f"recall_at_{k}": round(recall_at_k, 4),
        "mrr": round(mrr, 4),
    }

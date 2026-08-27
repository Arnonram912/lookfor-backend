"""Shared LookFor match scoring and dataset-level evaluation metrics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from collections import defaultdict
from datetime import date, datetime
from difflib import SequenceMatcher
import re
from typing import Any


IMAGE_WEIGHT = 0.60
TEXT_WEIGHT = 0.40

POSSIBLE_MATCH_THRESHOLD = 0.45
MATCH_THRESHOLD = 0.75

CLIP_SCORE_WEIGHT = 0.80
DETAIL_SCORE_WEIGHT = 0.20

# Ranked candidates receive a small confidence decay as their rank increases.
# Rank 1 keeps 100%, rank 2 keeps 95%, rank 3 keeps 90%, etc.
RANK_DECAY = 0.05

BRAND_CONFLICT_MULTIPLIER = 0.00
COLOR_CONFLICT_MULTIPLIER = 0.00
ITEM_TYPE_CATEGORY_OVERRIDE_THRESHOLD = 0.80


def clamp_similarity_score(value: Any) -> float:
    """Keep internal similarity values within the display-safe 0..1 range."""
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = 0.0
    return max(0.0, min(1.0, numeric_value))


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


_CATEGORY_ALIASES = {
    "electronic": "electronics",
    "electronic item": "electronics",
    "electronic items": "electronics",
    "bag and case": "bags and cases",
    "bag and cases": "bags and cases",
    "bags and case": "bags and cases",
    "personal item": "personal items",
}


def _canonical_category(value: Any) -> str:
    """Normalize category labels without treating partial names as equal."""
    normalized = _normalized_text(value)
    normalized = re.sub(r"\([^)]*\)", "", normalized)
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = " ".join(normalized.split())
    return _CATEGORY_ALIASES.get(normalized, normalized)


def calculate_category_similarity(left: Any, right: Any) -> float | None:
    """Return a separate exact-category signal.

    Case, punctuation, parenthetical examples, and a small set of equivalent
    labels are normalized. Substrings such as ``Accessories`` and
    ``Phone Accessories`` are deliberately different categories.
    """
    left_category = _canonical_category(left)
    right_category = _canonical_category(right)
    if not left_category or not right_category:
        return None
    return 1.0 if left_category == right_category else 0.0


def _text_field_similarity(left: Any, right: Any) -> float | None:
    """Return a conservative lexical similarity, or None when either field is absent."""
    normalized_left = _normalized_text(left)
    normalized_right = _normalized_text(right)
    if not normalized_left or not normalized_right:
        return None
    if normalized_left == normalized_right:
        return 1.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return 0.9

    left_tokens = set(normalized_left.split())
    right_tokens = set(normalized_right.split())
    token_union = left_tokens | right_tokens
    token_score = len(left_tokens & right_tokens) / len(token_union) if token_union else 0.0
    sequence_score = SequenceMatcher(None, normalized_left, normalized_right).ratio()
    return round(max(token_score, sequence_score), 4)


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def _time_minutes(value: Any) -> int | None:
    raw = str(value or "").strip()
    for pattern in ("%H:%M", "%H:%M:%S", "%I:%M %p"):
        try:
            parsed = datetime.strptime(raw, pattern)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue
    return None


def _event_time_similarity(
    left_date_value: Any,
    left_time_value: Any,
    right_date_value: Any,
    right_time_value: Any,
) -> float | None:
    """Compare date and time as one event timestamp when both are available."""
    left_date = _coerce_date(left_date_value)
    right_date = _coerce_date(right_date_value)
    if left_date is None or right_date is None:
        return None

    left_minutes = _time_minutes(left_time_value)
    right_minutes = _time_minutes(right_time_value)
    if left_minutes is not None and right_minutes is not None:
        left_event = datetime.combine(left_date, datetime.min.time())
        right_event = datetime.combine(right_date, datetime.min.time())
        difference_minutes = abs(
            int((left_event - right_event).total_seconds() / 60)
            + left_minutes
            - right_minutes
        )
        if difference_minutes <= 30:
            return 1.0
        if difference_minutes <= 60:
            return 0.9
        if difference_minutes <= 180:
            return 0.75
        if difference_minutes <= 720:
            return 0.4
        if difference_minutes <= 1440:
            return 0.25
        if difference_minutes <= 4320:
            return 0.1
        return 0.0

    days = abs((left_date - right_date).days)
    if days == 0:
        return 1.0
    if days == 1:
        return 0.75
    if days <= 3:
        return 0.4
    if days <= 7:
        return 0.15
    return 0.0


_COLOR_FAMILIES = {
    "black": "dark-neutral",
    "charcoal": "dark-neutral",
    "dark gray": "dark-neutral",
    "dark grey": "dark-neutral",
    "gray": "neutral",
    "grey": "neutral",
    "silver": "neutral",
    "white": "light-neutral",
    "cream": "light-neutral",
    "beige": "light-neutral",
    "navy": "dark-blue",
    "dark blue": "dark-blue",
    "blue": "blue",
}

_ITEM_TYPE_ALIASES = {
    "eyewear": ("eyeglasses", "eye glasses", "glasses", "spectacles"),
    "charger": ("charger", "charging cable", "power adapter", "power adaptor"),
    "sim-card": ("sim card", "simcard", "subscriber identity module"),
    "alcohol": ("alcohol", "rubbing alcohol", "isopropyl"),
}


def _canonical_item_type(value: Any) -> str | None:
    normalized = _normalized_text(value)
    for canonical, aliases in _ITEM_TYPE_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return canonical
    return None


def _item_type_similarity(left: Any, right: Any) -> float | None:
    lexical_score = _text_field_similarity(left, right)
    if lexical_score is None:
        return None
    left_type = _canonical_item_type(left)
    right_type = _canonical_item_type(right)
    if left_type and right_type:
        return 1.0 if left_type == right_type else 0.0
    return lexical_score


def _color_similarity(left: Any, right: Any) -> float | None:
    lexical_score = _text_field_similarity(left, right)
    if lexical_score is None or lexical_score == 1.0:
        return lexical_score
    normalized_left = _normalized_text(left)
    normalized_right = _normalized_text(right)
    left_family = _COLOR_FAMILIES.get(normalized_left)
    right_family = _COLOR_FAMILIES.get(normalized_right)
    if left_family and left_family == right_family:
        return 0.85
    if {left_family, right_family} == {"dark-neutral", "dark-blue"}:
        return 0.55
    return lexical_score


def calculate_detail_similarity(query: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[float | None, dict[str, float | None]]:
    """Compare item details explicitly so close place/date/time reports rank higher.

    Missing fields are ignored instead of being treated as mismatches. Description
    has a smaller structured weight because semantic description matching is already
    represented by the CLIP text score.
    """
    components = {
        "category_similarity": calculate_category_similarity(query.get("category"), candidate.get("category")),
        "item_type_similarity": _item_type_similarity(query.get("item_name"), candidate.get("item_name")),
        "location_similarity": _text_field_similarity(query.get("location"), candidate.get("location")),
        "brand_similarity": _text_field_similarity(query.get("brand"), candidate.get("brand")),
        "color_similarity": _color_similarity(query.get("color"), candidate.get("color")),
        "description_similarity": _text_field_similarity(query.get("description"), candidate.get("description")),
        "event_time_similarity": _event_time_similarity(
            query.get("date"),
            query.get("time_found"),
            candidate.get("date"),
            candidate.get("time_found"),
        ),
    }
    weights = {
        "category_similarity": 0.20,
        "item_type_similarity": 0.20,
        "location_similarity": 0.15,
        "brand_similarity": 0.12,
        "color_similarity": 0.08,
        "description_similarity": 0.10,
        "event_time_similarity": 0.15,
    }
    available_weight = sum(weights[name] for name, value in components.items() if value is not None)
    if not available_weight:
        return None, components
    score = sum(weights[name] * float(value) for name, value in components.items() if value is not None)
    return round(score / available_weight, 4), components


def calculate_detailed_match_score(image_similarity: float, text_similarity: float, detail_similarity: float | None) -> float:
    """Blend CLIP with explicit details while retaining legacy behavior if none exist."""
    clip_score = calculate_match_score(image_similarity, text_similarity)
    if detail_similarity is None:
        return clip_score
    score = (clip_score * CLIP_SCORE_WEIGHT) + (float(detail_similarity) * DETAIL_SCORE_WEIGHT)
    return round(clamp_similarity_score(score), 4)


def calculate_match_score(
    image_similarity: float,
    text_similarity: float,
) -> float:
    """Calculate the canonical image-text score used by every match flow."""
    score = (float(image_similarity) * IMAGE_WEIGHT) + (
        float(text_similarity) * TEXT_WEIGHT
    )
    return round(clamp_similarity_score(score), 4)


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


def apply_rank_decay(score: float, rank: int, decay: float = RANK_DECAY) -> float:
    """Reduce a candidate's displayed score according to its ranking position.

    Rank 1 keeps the original score. Each subsequent rank loses ``decay``
    fraction of the original score. The result is always clamped to 0..1.
    """
    if rank < 1:
        raise ValueError("rank must be at least 1.")
    if not 0.0 <= float(decay) <= 1.0:
        raise ValueError("decay must be between 0 and 1.")

    ranking_factor = max(0.0, 1.0 - ((rank - 1) * float(decay)))
    return round(clamp_similarity_score(float(score) * ranking_factor), 4)


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

        # Apply ranking decay after sorting so the best candidate remains unchanged.
        ranked = [
            (apply_rank_decay(score, rank), actual)
            for rank, (score, actual) in enumerate(ranked, start=1)
        ]

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

"""Persist unlabeled AI match observations without treating predictions as truth."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Iterable, Mapping


DEFAULT_OBSERVATIONS_PATH = Path(__file__).resolve().with_name("matching_observations.csv")

OBSERVATION_FIELDS = (
    "pair_key",
    "query_id",
    "lost_item_id",
    "found_item_id",
    "candidate_source",
    "observed_at",
    "image_similarity",
    "text_similarity",
    "detail_similarity",
    "raw_score",
    "final_confidence",
    "predicted_match",
    "query_visual_type",
    "candidate_visual_type",
    "visual_type_conflict",
    "item_type_conflict",
)

_dataset_lock = Lock()


def configured_observations_path() -> Path:
    configured = str(os.getenv("MATCHING_OBSERVATIONS_DATASET", "") or "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_OBSERVATIONS_PATH


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return [dict(row) for row in csv.DictReader(source)]


def _atomic_write(path: Path, fieldnames: Iterable[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    names = list(fieldnames)
    with temporary_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in names})
    os.replace(temporary_path, path)


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def record_match_observations(
    *,
    lost_item_id: int,
    found_item_id: int,
    candidate_source: str,
    candidates: Iterable[Mapping[str, Any]],
    path: Path | str | None = None,
) -> int:
    """Upsert scored pairs without claiming that the AI prediction is correct."""
    observation_path = Path(path) if path is not None else configured_observations_path()
    now = datetime.now(timezone.utc).isoformat()
    prepared: list[dict[str, str]] = []
    for candidate in candidates:
        candidate_lost_id = int(candidate.get("lost_item_id", lost_item_id))
        candidate_found_id = int(candidate.get("found_item_id", found_item_id))
        source = str(candidate.get("candidate_source", candidate_source) or candidate_source)
        pair_key = f"{candidate_lost_id}:{source}:{candidate_found_id}"
        prepared.append({
            "pair_key": pair_key,
            "query_id": f"lost-{candidate_lost_id}",
            "lost_item_id": str(candidate_lost_id),
            "found_item_id": str(candidate_found_id),
            "candidate_source": source,
            "observed_at": now,
            "image_similarity": _csv_value(candidate.get("image_similarity")),
            "text_similarity": _csv_value(candidate.get("text_similarity")),
            "detail_similarity": _csv_value(candidate.get("detail_similarity")),
            "raw_score": _csv_value(candidate.get("raw_score", candidate.get("score"))),
            "final_confidence": _csv_value(candidate.get("score")),
            "predicted_match": _csv_value(candidate.get("predicted_match", False)),
            "query_visual_type": _csv_value(candidate.get("query_visual_type")),
            "candidate_visual_type": _csv_value(candidate.get("candidate_visual_type")),
            "visual_type_conflict": _csv_value(candidate.get("visual_type_conflict", False)),
            "item_type_conflict": _csv_value(candidate.get("item_type_conflict", False)),
        })
    if not prepared:
        return 0

    with _dataset_lock:
        existing = _read_rows(observation_path)
        by_key = {row.get("pair_key", ""): row for row in existing if row.get("pair_key")}
        for row in prepared:
            by_key[row["pair_key"]] = row
        _atomic_write(observation_path, OBSERVATION_FIELDS, by_key.values())
    return len(prepared)

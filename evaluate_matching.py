"""Evaluate LookFor matching from a labeled CSV dataset.

Required columns: query_id,actual_match,image_similarity,text_similarity
Optional audit columns: brand_comparison,color_comparison,location_comparison.
Use same, different, or not_provided. These labels are descriptive and do not
change the score because the same details are already represented by text
similarity.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from matching_metrics import (
    MATCH_THRESHOLD,
    calculate_match_score,
    evaluate_match_dataset,
    evaluate_ranking_metrics,
)


TRUE_VALUES = {"1", "true", "yes", "y"}
FALSE_VALUES = {"0", "false", "no", "n"}


def parse_label(value: str, row_number: int) -> bool:
    normalized = str(value or "").strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(
        f"Row {row_number}: actual_match must be true/false, yes/no, or 1/0."
    )


def load_scored_dataset(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"query_id", "actual_match", "image_similarity", "text_similarity"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required CSV columns: {', '.join(sorted(missing))}")

        for row_number, row in enumerate(reader, start=2):
            try:
                score = calculate_match_score(
                    float(row["image_similarity"]),
                    float(row["text_similarity"]),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Row {row_number}: similarities must be numeric."
                ) from exc

            records.append(
                {
                    "query_id": str(row["query_id"] or "").strip(),
                    "actual_match": parse_label(row["actual_match"], row_number),
                    "score": score,
                }
            )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Calculate LookFor classification metrics, Recall@K, and MRR."
        )
    )
    parser.add_argument("dataset", type=Path, help="Path to the labeled CSV dataset")
    parser.add_argument(
        "--threshold",
        type=float,
        default=MATCH_THRESHOLD,
        help=f"Positive-match threshold (default: {MATCH_THRESHOLD})",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Candidate cutoff for Recall@K (default: 5)",
    )
    args = parser.parse_args()
    records = load_scored_dataset(args.dataset)
    metrics = evaluate_match_dataset(records, threshold=args.threshold)
    metrics.update(evaluate_ranking_metrics(records, k=args.k))
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

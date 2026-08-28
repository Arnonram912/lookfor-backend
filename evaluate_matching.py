"""Evaluate LookFor matching from a labeled CSV dataset.

Required columns: query_id,actual_match,image_similarity,text_similarity
Optional audit columns: brand_comparison,color_comparison,location_comparison.
Use same, different, or not_provided. These labels are descriptive and do not
change the score because the same details are already represented by text
similarity.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from automatic_match_evaluation import load_labeled_dataset
from matching_metrics import (
    MATCH_THRESHOLD,
    evaluate_match_dataset,
    evaluate_ranking_metrics,
)


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
        default=None,
        help="Optional extra Recall@K cutoff in addition to 1, 5, and 10",
    )
    args = parser.parse_args()
    records = load_labeled_dataset(args.dataset)
    metrics = evaluate_match_dataset(records, threshold=args.threshold)
    for cutoff in (1, 5, 10):
        metrics.update(evaluate_ranking_metrics(records, k=cutoff))
    if args.k is not None and args.k not in {1, 5, 10}:
        metrics.update(evaluate_ranking_metrics(records, k=args.k))
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

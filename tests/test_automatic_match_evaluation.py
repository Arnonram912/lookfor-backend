import json
import unittest
from types import SimpleNamespace

from automatic_match_evaluation import (
    calculate_automatic_match_evaluation,
    parse_claim_similarity,
)


class AutomaticMatchEvaluationTests(unittest.TestCase):
    def test_claim_similarity_parser_supports_saved_percentages(self):
        self.assertEqual(parse_claim_similarity("79.6%"), 0.796)
        self.assertEqual(parse_claim_similarity("AI MATCH (82.0%)"), 0.82)
        self.assertEqual(parse_claim_similarity(0.75), 0.75)
        self.assertIsNone(parse_claim_similarity("Manual Match"))

    def test_metrics_are_derived_from_decisions_and_saved_rankings(self):
        claims = [
            SimpleNamespace(id=1, lost_item_id=10, found_item_id=101, status="claimed", similarity_score="80%"),
            SimpleNamespace(id=2, lost_item_id=11, found_item_id=102, status="rejected", similarity_score="80%"),
            SimpleNamespace(id=3, lost_item_id=12, found_item_id=103, status="rejected", similarity_score="60%"),
            SimpleNamespace(id=4, lost_item_id=13, found_item_id=104, status="claimed", similarity_score="Manual Match"),
        ]
        lost_items = [
            SimpleNamespace(id=10, possible_matches=json.dumps([
                {"id": 105, "source": "found", "raw_score": 0.91},
                {"id": 101, "source": "found", "raw_score": 0.86},
            ])),
            SimpleNamespace(id=13, possible_matches=json.dumps([
                {"id": 104, "source": "found", "raw_score": 0.95},
            ])),
        ]

        metrics = calculate_automatic_match_evaluation(claims, lost_items)

        self.assertEqual(metrics["total"], 3)
        self.assertEqual(metrics["true_positive"], 1)
        self.assertEqual(metrics["false_positive"], 1)
        self.assertEqual(metrics["true_negative"], 1)
        self.assertEqual(metrics["decided_claims"], 4)
        self.assertEqual(metrics["scored_decisions"], 3)
        self.assertEqual(metrics["unscored_decisions"], 1)
        self.assertEqual(metrics["recall_at_1"], 0.5)
        self.assertEqual(metrics["recall_at_5"], 1.0)
        self.assertEqual(metrics["mrr"], 0.75)


if __name__ == "__main__":
    unittest.main()

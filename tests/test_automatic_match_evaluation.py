import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from automatic_match_evaluation import (
    calculate_labeled_dataset_evaluation,
    calculate_live_matching_analytics,
    load_labeled_dataset,
    parse_label,
)


HEADER = "query_id,actual_match,image_similarity,text_similarity\n"


class AutomaticMatchEvaluationTests(unittest.TestCase):
    def _dataset(self, contents: str) -> tuple[tempfile.TemporaryDirectory, Path]:
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "benchmark.csv"
        path.write_text(HEADER + contents, encoding="utf-8")
        return directory, path

    def test_label_parser_requires_explicit_ground_truth(self):
        self.assertTrue(parse_label("yes", 2))
        self.assertFalse(parse_label("0", 3))
        with self.assertRaisesRegex(ValueError, "actual_match"):
            parse_label("probably", 4)

    def test_dataset_scores_verified_pairs_with_production_formula(self):
        directory, path = self._dataset("lost-1,true,0.90,0.80\n")
        self.addCleanup(directory.cleanup)

        records = load_labeled_dataset(path)

        self.assertEqual(records, [{
            "query_id": "lost-1",
            "actual_match": True,
            "score": 0.86,
        }])

    def test_dataset_uses_recorded_production_score_when_available(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "benchmark.csv"
        path.write_text(
            "query_id,actual_match,image_similarity,text_similarity,score\n"
            "lost-1,true,0.90,0.80,0.77\n",
            encoding="utf-8",
        )

        self.assertEqual(load_labeled_dataset(path)[0]["score"], 0.77)

    def test_ready_metrics_come_only_from_fixed_labeled_dataset(self):
        directory, path = self._dataset(
            "lost-1,true,0.90,0.90\n"
            "lost-1,false,0.95,0.95\n"
            "lost-2,true,0.90,0.90\n"
            "lost-2,false,0.20,0.20\n"
        )
        self.addCleanup(directory.cleanup)

        metrics = calculate_labeled_dataset_evaluation(
            path, minimum_records=4, minimum_queries=2
        )

        self.assertEqual(metrics["source"], "fixed_labeled_dataset")
        self.assertEqual(metrics["dataset_status"], "ready")
        self.assertTrue(metrics["is_sufficient"])
        self.assertEqual(metrics["labeled_records"], 4)
        self.assertEqual(metrics["positive_records"], 2)
        self.assertEqual(metrics["negative_records"], 2)
        self.assertEqual(metrics["query_count"], 2)
        self.assertEqual(metrics["true_positive"], 2)
        self.assertEqual(metrics["false_positive"], 1)
        self.assertEqual(metrics["true_negative"], 1)
        self.assertEqual(metrics["recall_at_1"], 0.5)
        self.assertEqual(metrics["recall_at_5"], 1.0)
        self.assertEqual(metrics["mrr"], 0.75)

    def test_small_dataset_is_explicitly_preliminary(self):
        directory, path = self._dataset(
            "lost-1,true,0.90,0.90\n"
            "lost-1,false,0.20,0.20\n"
        )
        self.addCleanup(directory.cleanup)

        metrics = calculate_labeled_dataset_evaluation(path)

        self.assertEqual(metrics["dataset_status"], "insufficient_data")
        self.assertFalse(metrics["is_sufficient"])
        self.assertEqual(metrics["labeled_records"], 2)

    def test_missing_and_invalid_datasets_do_not_publish_fake_metrics(self):
        missing = calculate_labeled_dataset_evaluation(Path("does-not-exist.csv"))
        self.assertEqual(missing["dataset_status"], "missing")
        self.assertEqual(missing["labeled_records"], 0)

        directory, invalid_path = self._dataset("lost-1,true,1.5,0.80\n")
        self.addCleanup(directory.cleanup)
        invalid = calculate_labeled_dataset_evaluation(invalid_path)
        self.assertEqual(invalid["dataset_status"], "invalid")
        self.assertIn("between 0 and 1", invalid["dataset_error"])

    def test_live_ai_activity_uses_saved_clip_rankings_without_truth_labels(self):
        lost_items = [
            SimpleNamespace(
                is_matched=True,
                possible_matches=json.dumps([
                    {
                        "id": 101,
                        "source": "found",
                        "score": 0.78,
                        "raw_score": 0.81,
                        "image_similarity": 0.92,
                        "text_similarity": 0.84,
                        "detail_similarity": 0.75,
                        "visual_type_conflict": True,
                        "competition_decay": 0.03,
                    },
                    {
                        "id": 102,
                        "source": "pending_found",
                        "score": 0.74,
                        "raw_score": 0.74,
                    },
                ]),
            ),
            SimpleNamespace(is_matched=False, possible_matches=None),
            SimpleNamespace(is_matched=False, possible_matches="not-json"),
        ]

        activity = calculate_live_matching_analytics(lost_items)

        self.assertEqual(activity["source"], "saved_live_clip_rankings")
        self.assertEqual(activity["active_lost_reports"], 3)
        self.assertEqual(activity["reports_with_candidates"], 1)
        self.assertEqual(activity["reports_without_candidates"], 2)
        self.assertEqual(activity["matched_lost_reports"], 1)
        self.assertEqual(activity["saved_candidates"], 2)
        self.assertEqual(activity["threshold_candidates"], 1)
        self.assertEqual(activity["pending_found_candidates"], 1)
        self.assertEqual(activity["decayed_candidates"], 1)
        self.assertEqual(activity["visual_type_conflicts"], 1)
        self.assertEqual(activity["automatic_ready_reports"], 1)
        self.assertEqual(activity["average_top_confidence"], 0.78)
        self.assertEqual(activity["average_top_image_similarity"], 0.92)
        self.assertEqual(activity["average_top_text_similarity"], 0.84)
        self.assertEqual(activity["average_top_detail_similarity"], 0.75)
        self.assertEqual(activity["invalid_caches"], 1)

    def test_boolean_match_state_is_never_used_as_ai_confidence(self):
        activity = calculate_live_matching_analytics([
            SimpleNamespace(
                is_matched=True,
                possible_matches=json.dumps([{
                    "score": 0.63,
                    "image_similarity": 0.70,
                    "text_similarity": 0.58,
                    "detail_similarity": 0.61,
                }]),
            )
        ])

        self.assertEqual(activity["matched_lost_reports"], 1)
        self.assertEqual(activity["average_top_confidence"], 0.63)
        self.assertNotEqual(activity["average_top_confidence"], 1.0)

    def test_dashboard_does_not_expose_matching_metrics(self):
        dashboard = (
            Path(__file__).resolve().parents[1] / "templates" / "admin.20.html"
        ).read_text(encoding="utf-8")

        self.assertNotIn("AI Matching Evaluation", dashboard)
        self.assertNotIn("updateLiveClipMatchingActivity", dashboard)
        self.assertNotIn("matching-evaluation-metrics", dashboard)
        self.assertTrue((Path(__file__).resolve().parents[1] / "matching_dataset.csv").is_file())


if __name__ == "__main__":
    unittest.main()

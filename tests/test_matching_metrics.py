import unittest

from matching_metrics import (
    MATCH_THRESHOLD,
    calculate_category_similarity,
    calculate_competition_confidences,
    calculate_detail_similarity,
    calculate_detailed_match_score,
    calculate_match_score,
    clamp_similarity_score,
    evaluate_match_dataset,
    evaluate_ranking_metrics,
    is_match,
)


class MatchScoreTests(unittest.TestCase):
    def test_equal_candidates_share_confidence_without_artificial_rank_advantage(self):
        confidences = calculate_competition_confidences([0.9] * 100)
        self.assertEqual(set(confidences), {0.0826})

    def test_clear_winner_keeps_confidence_when_other_candidates_do_not_qualify(self):
        confidences = calculate_competition_confidences([0.9, 0.4, 0.2])
        self.assertEqual(confidences, [0.9, 0.0, 0.0])

    def test_clear_winner_remains_strong_among_many_weak_qualifiers(self):
        confidences = calculate_competition_confidences([0.9, *([0.5] * 99)])
        self.assertEqual(confidences[0], 0.9)
        self.assertTrue(all(value == 0.5 for value in confidences[1:]))

    def test_only_candidates_really_similar_to_the_best_apply_decay(self):
        confidences = calculate_competition_confidences([0.9, 0.88, 0.86, 0.7])

        self.assertLess(confidences[0], 0.9)
        self.assertLess(confidences[1], 0.88)
        # The third candidate does not participate in the near tie, but its
        # display confidence is capped to preserve the raw ranking order.
        self.assertEqual(confidences[2], confidences[1])
        self.assertEqual(confidences[3], 0.7)

    def test_candidate_outside_three_point_margin_does_not_decay_winner(self):
        confidences = calculate_competition_confidences([0.9, 0.8699])
        self.assertEqual(confidences, [0.9, 0.8699])

    def test_overall_near_tie_does_not_decay_when_images_are_not_close(self):
        confidences = calculate_competition_confidences(
            [0.9, 0.89],
            primary_similarity_scores=[1.0, 0.864],
        )
        self.assertEqual(confidences, [0.9, 0.89])

    def test_lower_rank_cannot_display_higher_adjusted_confidence(self):
        confidences = calculate_competition_confidences([0.9, 0.89, 0.85])
        self.assertGreaterEqual(confidences[0], confidences[1])
        self.assertGreaterEqual(confidences[1], confidences[2])

    def test_canonical_formula_uses_image_and_text_similarity(self):
        score = calculate_match_score(0.8, 0.6)
        self.assertEqual(score, 0.72)
        self.assertFalse(is_match(score))

    def test_low_image_and_text_similarity_stays_below_threshold(self):
        score = calculate_match_score(0.4, 0.3)
        self.assertEqual(score, 0.36)
        self.assertFalse(is_match(score))

    def test_default_threshold_is_standardized(self):
        self.assertEqual(MATCH_THRESHOLD, 0.75)
        self.assertTrue(is_match(MATCH_THRESHOLD))
        self.assertFalse(is_match(MATCH_THRESHOLD - 0.0001))
        self.assertFalse(is_match(0.74))

    def test_final_score_is_bounded_for_percentage_display(self):
        self.assertEqual(
            calculate_match_score(1.0, 1.0),
            1.0,
        )
        self.assertEqual(calculate_match_score(2.0, 2.0), 1.0)
        self.assertEqual(calculate_detailed_match_score(2.0, 2.0, 2.0), 1.0)
        self.assertEqual(clamp_similarity_score(1.74), 1.0)

    def test_details_compare_category_brand_color_and_combined_event_time(self):
        score, components = calculate_detail_similarity(
            {
                "category": "Wallet",
                "brand": "Acme",
                "color": "Black",
                "date": "2026-08-13",
                "time_found": "10:00",
            },
            {
                "category": "Wallet",
                "brand": "Acme",
                "color": "Charcoal",
                "date": "2026-08-13",
                "time_found": "10:20",
            },
        )

        self.assertEqual(components["category_similarity"], 1.0)
        self.assertEqual(components["brand_similarity"], 1.0)
        self.assertEqual(components["color_similarity"], 0.85)
        self.assertEqual(components["event_time_similarity"], 1.0)
        self.assertGreater(score, 0.95)

    def test_category_is_a_separate_exact_signal(self):
        self.assertEqual(
            calculate_category_similarity("Bags & Cases", "bags and cases"),
            1.0,
        )
        self.assertEqual(
            calculate_category_similarity(
                "Personal Items (Wallets/Keys)",
                "Personal Items",
            ),
            1.0,
        )
        self.assertEqual(
            calculate_category_similarity("Accessories", "Phone Accessories"),
            0.0,
        )


class MatchEvaluationTests(unittest.TestCase):
    def test_accuracy_precision_recall_and_f1(self):
        metrics = evaluate_match_dataset(
            [
                {"actual_match": True, "score": 0.90},
                {"actual_match": True, "score": 0.20},
                {"actual_match": False, "score": 0.80},
                {"actual_match": False, "score": 0.10},
            ]
        )

        self.assertEqual(metrics["true_positive"], 1)
        self.assertEqual(metrics["false_positive"], 1)
        self.assertEqual(metrics["true_negative"], 1)
        self.assertEqual(metrics["false_negative"], 1)
        self.assertEqual(metrics["accuracy"], 0.5)
        self.assertEqual(metrics["precision"], 0.5)
        self.assertEqual(metrics["recall"], 0.5)
        self.assertEqual(metrics["f1_score"], 0.5)

    def test_zero_division_returns_zero(self):
        metrics = evaluate_match_dataset(
            [{"actual_match": False, "score": 0.1}]
        )
        self.assertEqual(metrics["precision"], 0.0)
        self.assertEqual(metrics["recall"], 0.0)
        self.assertEqual(metrics["f1_score"], 0.0)

    def test_invalid_record_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_match_dataset([{"actual_match": "maybe", "score": 0.8}])

    def test_recall_at_k_and_mrr_use_per_query_rankings(self):
        metrics = evaluate_ranking_metrics(
            [
                {"query_id": "q1", "actual_match": False, "score": 0.90},
                {"query_id": "q1", "actual_match": True, "score": 0.80},
                {"query_id": "q1", "actual_match": True, "score": 0.70},
                {"query_id": "q2", "actual_match": True, "score": 0.95},
                {"query_id": "q2", "actual_match": False, "score": 0.85},
                {"query_id": "q3", "actual_match": False, "score": 0.60},
            ],
            k=2,
        )

        self.assertEqual(metrics["ranking_queries"], 3)
        self.assertEqual(metrics["ranking_queries_evaluated"], 2)
        self.assertEqual(metrics["queries_without_relevant"], 1)
        self.assertEqual(metrics["recall_at_2"], 0.75)
        self.assertEqual(metrics["mrr"], 0.75)

    def test_ranking_metrics_require_query_id(self):
        with self.assertRaises(ValueError):
            evaluate_ranking_metrics([{"actual_match": True, "score": 0.8}])

    def test_ranking_metrics_require_positive_k(self):
        with self.assertRaises(ValueError):
            evaluate_ranking_metrics([], k=0)


if __name__ == "__main__":
    unittest.main()

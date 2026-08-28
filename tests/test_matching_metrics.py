import unittest

from matching_metrics import (
    MATCH_THRESHOLD,
    calculate_category_similarity,
    calculate_competition_confidences,
    competition_decay_for_count,
    calculate_detail_similarity,
    calculate_detailed_match_score,
    calculate_match_score,
    clamp_similarity_score,
    evaluate_match_dataset,
    evaluate_ranking_metrics,
    is_automatic_match_candidate,
    is_match,
)


class MatchScoreTests(unittest.TestCase):
    def test_equal_candidates_share_confidence_without_artificial_rank_advantage(self):
        confidences = calculate_competition_confidences([0.9] * 100)
        self.assertEqual(set(confidences), {0.84})

    def test_diminishing_steps_form_one_cumulative_decay_total(self):
        self.assertEqual(competition_decay_for_count(1), 0.0)
        self.assertEqual(competition_decay_for_count(2), 0.03)
        self.assertEqual(competition_decay_for_count(3), 0.05)
        self.assertEqual(competition_decay_for_count(4), 0.06)
        self.assertEqual(competition_decay_for_count(5), 0.06)
        self.assertEqual(competition_decay_for_count(100), 0.06)
        self.assertEqual(calculate_competition_confidences([0.90] * 5), [0.84] * 5)

    def test_exactly_seventy_five_percent_is_an_automatic_match(self):
        self.assertTrue(is_automatic_match_candidate({
            "score": 0.75,
            "raw_score": 0.90,
            "competition_decay": 0.15,
            "available_for_match": True,
        }))
        self.assertTrue(is_automatic_match_candidate({
            "score": 0.75,
            "raw_score": 0.75,
            "competition_decay": 0.0,
            "available_for_match": True,
        }))
        self.assertFalse(is_automatic_match_candidate({
            "score": 0.7499,
            "raw_score": 0.7499,
            "competition_decay": 0.0,
            "available_for_match": True,
        }))

    def test_explicit_color_conflict_cannot_automatic_match(self):
        self.assertFalse(is_automatic_match_candidate({
            "score": 0.98,
            "raw_score": 0.98,
            "competition_decay": 0.0,
            "available_for_match": True,
            "color_conflict": True,
        }))

    def test_current_color_review_candidate_cannot_automatic_match(self):
        self.assertFalse(is_automatic_match_candidate({
            "score": 0.94,
            "raw_score": 0.94,
            "competition_decay": 0.0,
            "available_for_match": True,
            "color_conflict": True,
            "confirmed_color_conflict": False,
            "color_review_required": True,
        }))

    def test_reliable_visual_type_conflict_cannot_automatic_match(self):
        self.assertFalse(is_automatic_match_candidate({
            "score": 0.92,
            "raw_score": 0.92,
            "competition_decay": 0.0,
            "available_for_match": True,
            "visual_type_review_required": True,
        }))

    def test_decay_never_pushes_qualifying_candidate_below_seventy_five_percent(self):
        confidences = calculate_competition_confidences([0.91, 0.90, 0.89])
        self.assertTrue(all(confidence >= 0.75 for confidence in confidences))

    def test_floor_does_not_artificially_raise_a_lower_raw_score(self):
        confidences = calculate_competition_confidences([0.74, 0.73])
        self.assertEqual(confidences, [0.74, 0.73])

    def test_clear_winner_keeps_confidence_when_other_candidates_do_not_qualify(self):
        confidences = calculate_competition_confidences([0.9, 0.4, 0.2])
        self.assertEqual(confidences, [0.9, 0.0, 0.0])

    def test_clear_winner_remains_strong_among_many_weak_qualifiers(self):
        confidences = calculate_competition_confidences([0.9, *([0.5] * 99)])
        self.assertEqual(confidences[0], 0.9)
        self.assertTrue(all(value == 0.5 for value in confidences[1:]))

    def test_all_candidates_above_seventy_five_apply_group_decay(self):
        confidences = calculate_competition_confidences([0.9, 0.88, 0.86, 0.7])

        self.assertEqual(confidences[0], 0.85)
        self.assertEqual(confidences[1], 0.83)
        self.assertEqual(confidences[2], 0.81)
        self.assertEqual(confidences[3], 0.7)

    def test_distant_candidate_above_threshold_still_counts_for_decay(self):
        confidences = calculate_competition_confidences([0.9, 0.8699])
        self.assertEqual(confidences, [0.87, 0.8399])

    def test_mixed_example_counts_only_raw_scores_at_or_above_threshold(self):
        confidences = calculate_competition_confidences([0.98, 0.87, 0.85, 0.73])
        self.assertEqual(confidences, [0.93, 0.82, 0.80, 0.73])

    def test_exactly_seventy_five_percent_participates_but_stays_at_floor(self):
        confidences = calculate_competition_confidences([0.98, 0.75, 0.7499])
        self.assertEqual(confidences, [0.95, 0.75, 0.7499])

    def test_primary_image_gap_does_not_exclude_a_threshold_match_from_decay(self):
        confidences = calculate_competition_confidences(
            [0.9, 0.89],
            primary_similarity_scores=[1.0, 0.864],
        )
        self.assertEqual(confidences, [0.87, 0.86])

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

    def test_purple_and_violet_are_compatible_colors(self):
        _score, components = calculate_detail_similarity(
            {"color": "Purple"},
            {"color": "Violet"},
        )

        self.assertEqual(components["color_similarity"], 0.9167)

    def test_black_and_gray_are_compatible_neutral_shades(self):
        for gray_spelling in ("Gray", "Grey"):
            _score, components = calculate_detail_similarity(
                {"color": "Black"},
                {"color": gray_spelling},
            )

            with self.subTest(gray=gray_spelling):
                self.assertEqual(components["color_similarity"], 0.65)

    def test_color_wheel_similarity_decreases_with_hue_distance(self):
        similarities = []
        for candidate_color in ("Red", "Orange", "Yellow", "Green", "Cyan"):
            _score, components = calculate_detail_similarity(
                {"color": "Red"},
                {"color": candidate_color},
            )
            similarities.append(components["color_similarity"])

        self.assertEqual(similarities, [1.0, 0.8333, 0.6667, 0.3333, 0.0])

    def test_colored_and_neutral_values_are_a_hard_color_conflict(self):
        _score, components = calculate_detail_similarity(
            {"color": "Red"},
            {"color": "Black"},
        )

        self.assertEqual(components["color_similarity"], 0.0)

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

    def test_controlled_item_types_recognize_aliases_and_reject_other_types(self):
        same_type_score, same_components = calculate_detail_similarity(
            {"item_name": "iPad"},
            {"item_name": "Android tablet"},
        )
        different_type_score, different_components = calculate_detail_similarity(
            {"item_name": "portable charger"},
            {"item_name": "USB flash drive"},
        )

        self.assertEqual(same_components["item_type_similarity"], 1.0)
        self.assertEqual(same_type_score, 1.0)
        self.assertEqual(different_components["item_type_similarity"], 0.0)
        self.assertEqual(different_type_score, 0.0)

    def test_ring_name_does_not_misclassify_earrings(self):
        score, components = calculate_detail_similarity(
            {"item_name": "Gold earrings"},
            {"item_name": "Gold ring"},
        )

        self.assertEqual(components["item_type_similarity"], 0.0)
        self.assertEqual(score, 0.0)

    def test_watch_aliases_share_the_same_item_type(self):
        score, components = calculate_detail_similarity(
            {"item_name": "Black smartwatch"},
            {"item_name": "Black wrist watch"},
        )

        self.assertEqual(components["item_type_similarity"], 1.0)
        self.assertEqual(score, 1.0)

    def test_fan_aliases_share_the_same_item_type(self):
        score, components = calculate_detail_similarity(
            {"item_name": "White mini fan"},
            {"item_name": "Portable electric fan"},
        )

        self.assertEqual(components["item_type_similarity"], 1.0)
        self.assertEqual(score, 1.0)


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

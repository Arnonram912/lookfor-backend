import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from matching_metrics import MATCH_THRESHOLD
from main import (
    actively_linked_found_candidate_ids,
    cached_found_candidate_ids,
    classify_visual_color,
    classify_visual_item_type,
    compute_text_detail_matches,
)


class FakeQuery:
    def __init__(self, items):
        self.items = items

    def outerjoin(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.items


class FakeSession:
    def __init__(self, items):
        self.items = items

    def query(self, model, *args, **kwargs):
        from models import PendingItem

        return FakeQuery([] if model is PendingItem else self.items)


class ModelAwareFakeSession:
    def __init__(self, approved_items, pending_items):
        self.approved_items = approved_items
        self.pending_items = pending_items

    def query(self, model, *args, **kwargs):
        from models import PendingItem

        return FakeQuery(self.pending_items if model is PendingItem else self.approved_items)


def candidate(item_id, **overrides):
    values = dict(
        id=item_id,
        image_embedding=json.dumps([1.0, 0.0]),
        item_name=f"Wallet {item_id}",
        category="Wallet",
        category_relationship=None,
        department=None,
        brand="Acme",
        color="Black",
        location="Main Library",
        description="Black wallet",
        image_path="static/photos/boxw.png",
        date=None,
        time_found=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class MatchingScoreResponseTests(unittest.TestCase):
    def setUp(self):
        self.visual_classifier_patcher = patch(
            "main.classify_visual_item_type",
            return_value={
                "label": "wallet",
                "confidence": 0.90,
                "reliable": True,
            },
        )
        self.visual_classifier_patcher.start()
        self.addCleanup(self.visual_classifier_patcher.stop)
        self.visual_color_patcher = patch(
            "main.classify_visual_color", return_value=None
        )
        self.visual_color_patcher.start()
        self.addCleanup(self.visual_color_patcher.stop)

    @patch("main.get_text_embeddings")
    def test_clip_visual_classifier_can_identify_wallet_over_alcohol(self, text_embeddings):
        text_embeddings.side_effect = lambda prompts: np.asarray([
            [1.0, 0.0] if "wallet" in prompt.lower() else [0.0, 1.0]
            for prompt in prompts
        ])

        classification = classify_visual_item_type(np.array([1.0, 0.0]))

        self.assertEqual(classification["label"], "wallet")
        self.assertTrue(classification["reliable"])
        self.assertGreater(classification["confidence"], 0.9)

    @patch("main.get_text_embeddings")
    def test_clip_visual_color_classifier_can_identify_red(self, text_embeddings):
        text_embeddings.side_effect = lambda prompts: np.asarray([
            [1.0, 0.0] if " red" in prompt.lower() else [0.0, 1.0]
            for prompt in prompts
        ])

        classification = classify_visual_color(np.array([1.0, 0.0]))

        self.assertEqual(classification["label"], "red")
        self.assertTrue(classification["reliable"])
        self.assertGreater(classification["confidence"], 0.9)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_confident_visual_type_disagreement_requires_review(self, _text_embedding):
        with patch(
            "main.classify_visual_item_type",
            side_effect=[
                {"label": "wallet", "confidence": 0.91, "reliable": True},
                {"label": "rubbing alcohol bottle", "confidence": 0.88, "reliable": True},
            ],
        ):
            result = compute_text_detail_matches(
                FakeSession([candidate(77)]),
                category="Wallet",
                item_name="Wallet",
                location="Main Library",
                description="Black wallet",
                brand=None,
                color="Black",
                status="lost",
                search_vec=np.array([1.0, 0.0]),
                query_text_vec=np.array([1.0, 0.0]),
            )

        evaluated = result["ranked_candidates"][0]
        self.assertTrue(evaluated["visual_type_conflict"])
        self.assertFalse(evaluated["visual_type_agreement_confirmed"])
        self.assertTrue(evaluated["visual_type_review_required"])
        self.assertEqual(evaluated["query_visual_type"], "wallet")
        self.assertEqual(evaluated["candidate_visual_type"], "rubbing alcohol bottle")
        self.assertGreaterEqual(evaluated["score"], 0.45)
        self.assertIn("admin review is required", evaluated["warning"])
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["matched_items"][0]["id"], 77)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_uncertain_visual_type_difference_requires_review(self, _text_embedding):
        with patch(
            "main.classify_visual_item_type",
            side_effect=[
                {"label": "wallet", "confidence": 0.40, "reliable": False},
                {"label": "rubbing alcohol bottle", "confidence": 0.39, "reliable": False},
            ],
        ):
            result = compute_text_detail_matches(
                FakeSession([candidate(78)]),
                category="Wallet",
                item_name="Wallet",
                location="Main Library",
                description="Black wallet",
                brand=None,
                color="Black",
                status="lost",
                search_vec=np.array([1.0, 0.0]),
                query_text_vec=np.array([1.0, 0.0]),
            )

        evaluated = result["ranked_candidates"][0]
        self.assertFalse(evaluated["visual_type_conflict"])
        self.assertFalse(evaluated["visual_type_agreement_confirmed"])
        self.assertTrue(evaluated["visual_type_review_required"])
        self.assertGreaterEqual(evaluated["score"], MATCH_THRESHOLD)
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["matched_items"][0]["id"], 78)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_reliable_same_visual_type_can_automatic_match(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(79)]),
            category="Wallet",
            item_name="Wallet",
            location="Main Library",
            description="Black wallet",
            brand=None,
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        evaluated = result["ranked_candidates"][0]
        self.assertTrue(evaluated["visual_type_agreement_confirmed"])
        self.assertFalse(evaluated["visual_type_review_required"])
        self.assertEqual(result["matched_item"]["id"], 79)

    def test_cached_approved_match_is_retained_for_reanalysis(self):
        item = SimpleNamespace(possible_matches=json.dumps([
            {"id": 1116, "source": "found", "score": 0.91},
            {"id": 44, "source": "pending_found", "score": 0.82},
            {"id": "invalid", "source": "found"},
        ]))
        self.assertEqual(cached_found_candidate_ids(item), {1116})

    def test_active_claim_recovers_match_removed_from_cache(self):
        db = FakeSession([(1116,), (None,)])
        self.assertEqual(actively_linked_found_candidate_ids(db, 7162), {1116})

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_matched_candidate_is_analyzed_but_unavailable_for_second_claim(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(1116, is_matched=True)]),
            category="Wallet",
            item_name="Wallet 1116",
            location="Main Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        analyzed = result["ranked_candidates"][0]
        self.assertTrue(analyzed["is_already_matched"])
        self.assertFalse(analyzed["available_for_match"])
        self.assertEqual(result["matched_items"][0]["id"], 1116)
        self.assertIsNone(result["matched_item"])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_final_claim_excludes_candidate_even_if_match_flag_is_stale(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(1117, is_matched=False, found_item_id=1117)]),
            category="Wallet",
            item_name="Wallet 1117",
            location="Main Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        self.assertEqual(result["ranked_candidates"], [])
        self.assertIsNone(result["matched_item"])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_own_existing_match_remains_available_during_reanalysis(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(1116, is_matched=True)]),
            category="Wallet",
            item_name="Wallet 1116",
            location="Main Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
            include_candidate_ids={1116},
        )

        analyzed = result["ranked_candidates"][0]
        self.assertTrue(analyzed["available_for_match"])
        self.assertEqual(result["matched_item"]["id"], 1116)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_seventy_four_percent_is_possible_but_not_automatic(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(1)]),
            category="Wallet",
            item_name="Wallet 1",
            location="Main Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([0.675, 0.0]),
            query_text_vec=np.array([0.675, 0.0]),
        )

        self.assertEqual(result["highest_score"], 0.74)
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["matched_items"][0]["id"], 1)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_response_exposes_component_scores_top_ten_and_review_top_five(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(index) for index in range(1, 12)]),
            category="Wallet",
            location="Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        self.assertEqual(len(result["ranked_candidates"]), 10)
        self.assertEqual(len(result["matched_items"]), 5)
        top = result["ranked_candidates"][0]
        second = result["ranked_candidates"][1]
        self.assertEqual(top["rank"], 1)
        self.assertEqual(second["rank"], 2)
        self.assertAlmostEqual(top["score"], second["score"])
        self.assertGreater(second["competition_decay"], 0)
        self.assertEqual(top["image_similarity"], 1.0)
        self.assertEqual(top["text_similarity"], 1.0)
        self.assertGreater(top["detail_similarity"], 0.9)
        self.assertEqual(top["brand_similarity"], 1.0)
        self.assertGreater(top["raw_score"], 0.98)
        self.assertEqual(result["matched_item"]["id"], 1)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_same_location_date_time_and_brand_rank_closest_candidate_first(self, _text_embedding):
        far = candidate(
            1,
            location="Gym",
            brand="Other",
            description="Different wallet",
            date="2026-07-01",
            time_found="18:00",
        )
        close = candidate(
            2,
            date="2026-08-13",
            time_found="10:15",
        )
        result = compute_text_detail_matches(
            FakeSession([far, close]),
            category="Wallet",
            location="Main Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            date_value="2026-08-13",
            time_found="10:00",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        self.assertEqual(result["matched_item"]["id"], 2)
        self.assertEqual(result["matched_item"]["detail_similarity"], 1.0)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_lost_analysis_includes_pending_found_candidates(self, _text_embedding):
        pending = candidate(99)
        result = compute_text_detail_matches(
            ModelAwareFakeSession([], [pending]),
            category="Wallet",
            location="Room 201",
            description="Eyeglasses",
            brand=None,
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        self.assertEqual(result["matched_item"]["id"], 99)
        self.assertEqual(result["matched_item"]["source"], "pending_found")

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_pending_found_reserved_for_another_lost_item_is_visible_but_unavailable(self, _text_embedding):
        pending = candidate(100, matched_item_id=777)
        result = compute_text_detail_matches(
            ModelAwareFakeSession([], [pending]),
            category="Wallet",
            item_name="Wallet",
            location="Room 201",
            description="Black wallet",
            brand=None,
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
            current_lost_item_id=888,
        )

        analyzed = result["ranked_candidates"][0]
        self.assertEqual(analyzed["id"], 100)
        self.assertTrue(analyzed["is_already_matched"])
        self.assertFalse(analyzed["available_for_match"])
        self.assertEqual(result["matched_items"][0]["id"], 100)
        self.assertIsNone(result["matched_item"])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_pending_found_reserved_for_same_lost_item_remains_on_reanalysis(self, _text_embedding):
        pending = candidate(101, matched_item_id=777)
        result = compute_text_detail_matches(
            ModelAwareFakeSession([], [pending]),
            category="Wallet",
            item_name="Wallet",
            location="Room 201",
            description="Black wallet",
            brand=None,
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
            current_lost_item_id=777,
        )

        self.assertEqual(result["ranked_candidates"][0]["id"], 101)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_unrelated_category_cannot_auto_match_even_with_high_clip_score(self, _text_embedding):
        alcohol = candidate(
            5,
            item_name="Alcohol bottle",
            category="Alcohol",
            category_relationship=None,
            brand="CleanCo",
            color="Clear",
            description="Bottle of rubbing alcohol",
        )
        result = compute_text_detail_matches(
            FakeSession([alcohol]),
            category="SIM Card",
            item_name="SIM Card",
            location="Main Library",
            description="Black SIM card",
            brand="Telco",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        candidate_result = result["ranked_candidates"][0]
        self.assertTrue(candidate_result["cross_category"])
        self.assertLess(candidate_result["score"], 0.45)
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["matched_items"], [])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_exact_item_type_can_automatically_match_across_categories(self, _text_embedding):
        found_case = candidate(
            12,
            item_name="Eyeglasses case",
            category="Personal Items (Wallets/Keys)",
            category_relationship=None,
            brand=None,
            color="Cream",
            description="Case with sticker",
        )
        result = compute_text_detail_matches(
            FakeSession([found_case]),
            category="Bags & Cases",
            item_name="Eyeglasses case",
            location="6th floor",
            description="With eyeglass inside",
            brand=None,
            color="Cream",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        candidate_result = result["ranked_candidates"][0]
        self.assertTrue(candidate_result["cross_category"])
        self.assertTrue(candidate_result["category_overridden_by_item_type"])
        self.assertGreaterEqual(candidate_result["score"], MATCH_THRESHOLD)
        self.assertEqual(result["matched_item"]["id"], 12)
        self.assertEqual(result["matched_items"][0]["id"], 12)
        self.assertIn("category does not block", candidate_result["warning"])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_eyeglasses_cannot_match_charger_inside_same_broad_category(self, _text_embedding):
        charger = candidate(
            6,
            item_name="Phone charger",
            category="Accessories",
            category_relationship=None,
            description="USB phone power adapter",
        )
        result = compute_text_detail_matches(
            FakeSession([charger]),
            category="Accessories",
            item_name="Eyeglasses",
            location="Main Library",
            description="Black reading glasses",
            brand=None,
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        candidate_result = result["ranked_candidates"][0]
        self.assertFalse(candidate_result["cross_category"])
        self.assertTrue(candidate_result["category_match"])
        self.assertTrue(candidate_result["item_type_conflict"])
        self.assertLess(candidate_result["score"], 0.45)
        self.assertIsNone(result["matched_item"])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_alcohol_cannot_match_wallet_inside_same_broad_category(self, _text_embedding):
        wallet = candidate(
            13,
            item_name="Wallet",
            category="Personal Items (Wallets/Keys)",
            category_relationship=None,
            location="Canteen",
            description=None,
        )
        result = compute_text_detail_matches(
            FakeSession([wallet]),
            category="Personal Items (Wallets/Keys)",
            item_name="Alcohol",
            location="Canteen",
            description=None,
            brand=None,
            color="Green",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        candidate_result = result["ranked_candidates"][0]
        self.assertTrue(candidate_result["category_match"])
        self.assertTrue(candidate_result["item_type_conflict"])
        self.assertLess(candidate_result["score"], 0.45)
        self.assertEqual(result["matched_items"], [])
        self.assertIsNone(result["matched_item"])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_different_jewelry_types_do_not_match(self, _text_embedding):
        ring = candidate(
            14,
            item_name="Gold ring",
            category="Jewelry",
            category_relationship=None,
            location="Canteen",
            description=None,
        )
        result = compute_text_detail_matches(
            FakeSession([ring]),
            category="Jewelry",
            item_name="Bracelet",
            location="Canteen",
            description=None,
            brand=None,
            color="Gold",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        candidate_result = result["ranked_candidates"][0]
        self.assertTrue(candidate_result["item_type_conflict"])
        self.assertLess(candidate_result["score"], 0.45)
        self.assertEqual(result["matched_items"], [])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_observation_capture_retains_all_scored_candidates(self, _text_embedding):
        candidates = [candidate(item_id) for item_id in range(200, 212)]
        result = compute_text_detail_matches(
            FakeSession(candidates),
            category="Wallet",
            item_name="Wallet",
            location="Main Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
            include_observation_candidates=True,
        )

        self.assertEqual(len(result["ranked_candidates"]), 10)
        self.assertEqual(len(result["_observation_candidates"]), 12)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_brand_conflict_does_not_change_score(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(7, brand="Other Brand")]),
            category="Wallet",
            item_name="Wallet 7",
            location="Main Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )
        control = compute_text_detail_matches(
            FakeSession([candidate(7)]),
            category="Wallet",
            item_name="Wallet 7",
            location="Main Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        candidate_result = result["ranked_candidates"][0]
        self.assertTrue(candidate_result["brand_conflict"])
        self.assertEqual(candidate_result["score"], control["ranked_candidates"][0]["score"])
        self.assertEqual(result["matched_item"]["id"], 7)
        self.assertEqual(result["matched_items"][0]["id"], 7)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_unconfirmed_reported_color_conflict_requires_review(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(8, color="Red")]),
            category="Wallet",
            item_name="Wallet 8",
            location="Main Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )
        candidate_result = result["ranked_candidates"][0]
        self.assertTrue(candidate_result["color_conflict"])
        self.assertFalse(candidate_result["confirmed_color_conflict"])
        self.assertTrue(candidate_result["color_review_required"])
        self.assertGreaterEqual(candidate_result["raw_score"], 0.45)
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["matched_items"][0]["id"], 8)
        self.assertIn("admin review is required", candidate_result["warning"])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_brand_and_unconfirmed_color_conflicts_remain_reviewable(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(9, brand="Other Brand", color="Brown")]),
            category="Wallet",
            item_name="Wallet 9",
            location="Main Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        candidate_result = result["ranked_candidates"][0]
        self.assertTrue(candidate_result["brand_conflict"])
        self.assertTrue(candidate_result["color_conflict"])
        self.assertTrue(candidate_result["color_review_required"])
        self.assertGreaterEqual(candidate_result["score"], 0.45)
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["matched_items"][0]["id"], 9)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_written_and_reliable_visual_color_conflict_blocks_match(self, _text_embedding):
        with patch(
            "main.classify_visual_color",
            side_effect=[
                {"label": "black", "confidence": 0.91, "reliable": True},
                {"label": "red", "confidence": 0.89, "reliable": True},
            ],
        ):
            result = compute_text_detail_matches(
                FakeSession([candidate(18, color="Red")]),
                category="Wallet",
                item_name="Wallet 18",
                location="Main Library",
                description="Black wallet",
                brand="Acme",
                color="Black",
                status="lost",
                search_vec=np.array([1.0, 0.0]),
                query_text_vec=np.array([1.0, 0.0]),
            )

        candidate_result = result["ranked_candidates"][0]
        self.assertTrue(candidate_result["color_conflict"])
        self.assertTrue(candidate_result["visual_color_conflict"])
        self.assertTrue(candidate_result["confirmed_color_conflict"])
        self.assertFalse(candidate_result["color_review_required"])
        self.assertLess(candidate_result["raw_score"], 0.45)
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["matched_items"], [])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_incorrect_entered_color_does_not_hide_visual_match(self, _text_embedding):
        with patch(
            "main.classify_visual_color",
            side_effect=[
                {"label": "black", "confidence": 0.92, "reliable": True},
                {"label": "black", "confidence": 0.90, "reliable": True},
            ],
        ):
            result = compute_text_detail_matches(
                FakeSession([candidate(19, color="Black")]),
                category="Wallet",
                item_name="Wallet 19",
                location="Main Library",
                description="Wallet entered as red but photographed as black",
                brand="Acme",
                color="Red",
                status="lost",
                search_vec=np.array([1.0, 0.0]),
                query_text_vec=np.array([1.0, 0.0]),
            )

        candidate_result = result["ranked_candidates"][0]
        self.assertTrue(candidate_result["color_conflict"])
        self.assertFalse(candidate_result["visual_color_conflict"])
        self.assertFalse(candidate_result["confirmed_color_conflict"])
        self.assertTrue(candidate_result["color_review_required"])
        self.assertEqual(result["matched_items"][0]["id"], 19)
        self.assertIsNone(result["matched_item"])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_purple_and_violet_wallets_remain_match_eligible(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(9, color="Violet")]),
            category="Wallet",
            item_name="Wallet 9",
            location="Main Library",
            description="Purple wallet",
            brand="Acme",
            color="Purple",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        candidate_result = result["ranked_candidates"][0]
        self.assertFalse(candidate_result["color_conflict"])
        self.assertEqual(candidate_result["color_similarity"], 0.9167)
        self.assertEqual(result["matched_item"]["id"], 9)
        self.assertEqual(result["matched_items"][0]["id"], 9)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_location_difference_remains_passable(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(10, location="Gym")]),
            category="Wallet",
            item_name="Wallet 10",
            location="Main Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        candidate_result = result["ranked_candidates"][0]
        self.assertLess(candidate_result["location_similarity"], 0.35)
        self.assertGreaterEqual(candidate_result["score"], 0.75)
        self.assertEqual(result["matched_item"]["id"], 10)


if __name__ == "__main__":
    unittest.main()

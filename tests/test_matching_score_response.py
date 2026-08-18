import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from main import compute_text_detail_matches


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

    def query(self, *args, **kwargs):
        return FakeQuery(self.items)


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
        self.assertEqual(top["image_similarity"], 1.0)
        self.assertEqual(top["text_similarity"], 1.0)
        self.assertGreater(top["detail_similarity"], 0.9)
        self.assertEqual(top["brand_similarity"], 1.0)
        self.assertGreater(top["score"], 0.98)
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
    def test_exact_item_type_keeps_cross_category_candidate_for_review(self, _text_embedding):
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
        self.assertEqual(candidate_result["score"], 0.7499)
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["matched_items"][0]["id"], 12)
        self.assertIn("item type strongly agrees", candidate_result["warning"])

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
        self.assertTrue(candidate_result["item_type_conflict"])
        self.assertLess(candidate_result["score"], 0.45)
        self.assertIsNone(result["matched_item"])

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_brand_conflict_requires_admin_review(self, _text_embedding):
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

        candidate_result = result["ranked_candidates"][0]
        self.assertTrue(candidate_result["brand_conflict"])
        self.assertEqual(candidate_result["score"], 0.7499)
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["matched_items"][0]["id"], 7)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_color_conflict_requires_admin_review(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(8, color="Brown")]),
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
        self.assertEqual(candidate_result["score"], 0.7499)
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["matched_items"][0]["id"], 8)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_brand_and_color_conflict_cannot_be_a_possible_match(self, _text_embedding):
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
        self.assertLess(candidate_result["score"], 0.45)
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["matched_items"], [])

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

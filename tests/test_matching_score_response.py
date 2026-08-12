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


def candidate(item_id):
    return SimpleNamespace(
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
    )


class MatchingScoreResponseTests(unittest.TestCase):
    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_response_exposes_component_scores_and_top_five(self, _text_embedding):
        result = compute_text_detail_matches(
            FakeSession([candidate(index) for index in range(1, 7)]),
            category="Wallet",
            location="Library",
            description="Black wallet",
            brand="Acme",
            color="Black",
            status="lost",
            search_vec=np.array([1.0, 0.0]),
            query_text_vec=np.array([1.0, 0.0]),
        )

        self.assertEqual(len(result["ranked_candidates"]), 5)
        top = result["ranked_candidates"][0]
        self.assertEqual(top["image_similarity"], 1.0)
        self.assertEqual(top["text_similarity"], 1.0)
        self.assertNotIn("metadata_adjustment", top)
        self.assertEqual(top["score"], 1.0)
        self.assertEqual(result["matched_item"]["id"], 1)

    @patch("main.get_text_embedding", return_value=np.array([1.0, 0.0]))
    def test_lost_analysis_includes_pending_found_candidates(self, _text_embedding):
        pending = candidate(99)
        result = compute_text_detail_matches(
            ModelAwareFakeSession([], [pending]),
            category="Other",
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


if __name__ == "__main__":
    unittest.main()

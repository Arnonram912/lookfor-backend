import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from admin_routes import get_cached_found_match_evaluations


TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "templates"
    / "Admin Pages"
    / "Found_item_Report.html"
)


class FakeQuery:
    def __init__(self, items):
        self.items = items

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.items


class FakeSession:
    def __init__(self, lost_items):
        self.lost_items = lost_items

    def query(self, *args, **kwargs):
        return FakeQuery(self.lost_items)


def lost_item(item_id, score, found_id=44, source="found"):
    return SimpleNamespace(
        id=item_id,
        item_id=item_id,
        item_code=f"LOST-{item_id:06d}",
        status="lost",
        item_name="Black Wallet",
        category="Wallet",
        location="Main Library",
        image_path="static/photos/boxw.png",
        brand="Acme",
        color="Black",
        description="Wallet with ID",
        possible_matches=json.dumps([
            {
                "id": found_id,
                "source": source,
                "score": score,
                "image_similarity": 0.8,
                "text_similarity": 0.7,
                "detail_similarity": 0.9,
            }
        ]),
    )


class AdminFoundMatchEvaluationTests(unittest.TestCase):
    def test_reverse_lookup_returns_ranked_lost_candidates_with_components(self):
        db = FakeSession([
            lost_item(2, 0.63),
            lost_item(1, 0.81),
            lost_item(3, 0.95, found_id=99),
        ])

        evaluations = get_cached_found_match_evaluations(
            db,
            found_item_id=44,
            source="found",
        )

        self.assertEqual([match["id"] for match in evaluations], [1, 2])
        self.assertEqual(evaluations[0]["score"], 0.81)
        self.assertEqual(evaluations[0]["detail_similarity"], 0.9)

    def test_pending_and_approved_sources_do_not_mix(self):
        db = FakeSession([
            lost_item(1, 0.82, source="pending_found"),
            lost_item(2, 0.79, source="found"),
        ])

        evaluations = get_cached_found_match_evaluations(
            db,
            found_item_id=44,
            source="pending_found",
        )

        self.assertEqual([match["id"] for match in evaluations], [1])

    def test_found_admin_modal_loads_protected_evaluation_endpoint(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("AI Match Evaluation (Admin Only)", html)
        self.assertIn("/admin/items/found/${item.id}/match-evaluation", html)
        self.assertIn("'Authorization': `Bearer ${sessionStorage.getItem('admin_token')}`", html)
        self.assertIn("Eligible for automatic match — not linked", html)
        self.assertIn("Automatic match linked — pending claim created", html)


if __name__ == "__main__":
    unittest.main()

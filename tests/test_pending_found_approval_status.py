import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class PendingFoundApprovalStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routes = (ROOT / "admin_routes.py").read_text(encoding="utf-8")
        cls.template = (
            ROOT / "templates" / "Admin Pages" / "Found_item_Report.html"
        ).read_text(encoding="utf-8")

    def test_linked_pending_item_returns_matched_final_state(self):
        self.assertIn('final_status = "matched" if matched_lost_item else "approved"', self.routes)
        self.assertIn('"is_matched": bool(matched_lost_item)', self.routes)
        self.assertIn('"Pending item approved and moved directly to Matched."', self.routes)

    def test_approval_links_only_when_approved_item_is_current_top_candidate(self):
        self.assertIn('top_candidate = (', self.routes)
        self.assertIn('ranked_candidates[0]', self.routes)
        self.assertIn('top_candidate.get("id") == new_item.id', self.routes)
        self.assertIn('is_automatic_match_candidate(top_candidate)', self.routes)
        self.assertNotIn(
            'serialize_found_item_match(\n                new_item, MATCH_THRESHOLD',
            self.routes,
        )

    def test_approval_dialog_uses_returned_final_state(self):
        self.assertIn("result.is_matched ? 'Item matched' : 'Item approved'", self.template)


if __name__ == "__main__":
    unittest.main()

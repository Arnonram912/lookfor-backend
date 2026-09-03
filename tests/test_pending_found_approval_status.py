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

    def test_approved_pending_item_retains_ai_match_without_claim(self):
        self.assertIn('"item_status": "matched" if legacy_reserved_lost_item else "approved"', self.routes)
        self.assertIn('"is_matched": bool(legacy_reserved_lost_item)', self.routes)
        self.assertIn(
            '"Item approved with its AI match retained. Select the correct item from Possible Matches to create the claim."',
            self.routes,
        )

    def test_approval_does_not_automatically_create_a_claim(self):
        approval_block = self.routes.split('@router.post("/approve-item/{item_id}")', 1)[1]
        approval_block = approval_block.split('@router.post(', 1)[0]
        self.assertNotIn('ensure_pending_claim_for_pair(', approval_block)
        self.assertNotIn('authorize_single_ai_link(', approval_block)
        self.assertIn('select it from Possible Matches', approval_block)

    def test_approval_dialog_uses_returned_final_state(self):
        self.assertIn("result.is_matched ? 'Item matched' : 'Item approved'", self.template)


if __name__ == "__main__":
    unittest.main()

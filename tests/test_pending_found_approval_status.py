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

    def test_approval_dialog_uses_returned_final_state(self):
        self.assertIn("result.is_matched ? 'Item matched' : 'Item approved'", self.template)


if __name__ == "__main__":
    unittest.main()

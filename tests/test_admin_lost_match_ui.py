import re
import unittest
from pathlib import Path


TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "templates"
    / "Admin Pages"
    / "Lost_item_Report.html"
)


class AdminLostMatchUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_detail_view_uses_dedicated_possible_matches_button_and_modal(self):
        self.assertIn('id="viewPossibleMatchesBtn"', self.html)
        self.assertIn('id="detailPossibleMatchesModal"', self.html)
        self.assertIn('id="modalPossibleMatches"', self.html)

    def test_admin_can_select_exactly_one_possible_match(self):
        self.assertIn('type="radio" name="detailPossibleMatch"', self.html)
        self.assertIn('id="applySelectedMatchBtn"', self.html)
        self.assertIn("fetch('/api/admin/manual-claim'", self.html)

    def test_active_upload_handler_shows_results_after_closing_review(self):
        handler = re.search(
            r"async function executeSubmit\(\) \{(?P<body>.*?)\n\}\nasync function disposeItem",
            self.html,
            re.DOTALL,
        )
        self.assertIsNotNone(handler)
        body = handler.group("body")
        close_index = body.index("closeModal('confirmModal');")
        results_index = body.index("selectedMatch = await showMatchResultsModal")
        self.assertLess(close_index, results_index)


if __name__ == "__main__":
    unittest.main()

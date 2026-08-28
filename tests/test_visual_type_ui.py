import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATCH_RESULT_TEMPLATES = (
    ROOT / "templates" / "Student Pages" / "Student_LostReport.html",
    ROOT / "templates" / "Admin Pages" / "Lost_item_Report.html",
)
FOUND_DETAIL_TEMPLATE = ROOT / "templates" / "Admin Pages" / "Found_item_Report.html"


class VisualTypeUiTests(unittest.TestCase):
    def test_unreliable_classification_is_labeled_as_a_top_guess(self):
        for template in MATCH_RESULT_TEMPLATES:
            html = template.read_text(encoding="utf-8")
            with self.subTest(template=template.name):
                self.assertIn("candidate_visual_type_reliable === true", html)
                self.assertIn("uncertain (top guess:", html)
                self.assertNotIn("CLIP sees", html)

    def test_found_item_detail_hides_clip_visual_type_guesses(self):
        html = FOUND_DETAIL_TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn("candidate_visual_type_reliable === true", html)
        self.assertNotIn("uncertain (top guess:", html)
        self.assertNotIn("Visual type — Lost:", html)


if __name__ == "__main__":
    unittest.main()

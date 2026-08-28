import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = (
    ROOT / "templates" / "Student Pages" / "Student_LostReport.html",
    ROOT / "templates" / "Admin Pages" / "Lost_item_Report.html",
    ROOT / "templates" / "Admin Pages" / "Found_item_Report.html",
)


class VisualTypeUiTests(unittest.TestCase):
    def test_unreliable_classification_is_labeled_as_a_top_guess(self):
        for template in TEMPLATES:
            html = template.read_text(encoding="utf-8")
            with self.subTest(template=template.name):
                self.assertIn("candidate_visual_type_reliable === true", html)
                self.assertIn("uncertain (top guess:", html)
                self.assertNotIn("CLIP sees", html)


if __name__ == "__main__":
    unittest.main()

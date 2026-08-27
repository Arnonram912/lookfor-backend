import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class FoundDetailModalScrollTests(unittest.TestCase):
    def test_detail_modal_is_vertically_scrollable(self):
        css = (ROOT / "static" / "Found_item_report.css").read_text(encoding="utf-8")
        template = (
            ROOT / "templates" / "Admin Pages" / "Found_item_Report.html"
        ).read_text(encoding="utf-8")

        detail_rule = css.split(".detail-modal {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow-y: auto", detail_rule)
        self.assertIn("overflow-x: hidden", detail_rule)
        self.assertIn("Found_item_report.css?v=23", template)


if __name__ == "__main__":
    unittest.main()

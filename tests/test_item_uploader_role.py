import pathlib
import unittest
from types import SimpleNamespace

from utils import format_report_owner_role_label, format_user_role_label


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ItemUploaderRoleTests(unittest.TestCase):
    def test_role_label_prefers_authoritative_account_category(self):
        faculty = SimpleNamespace(
            is_admin=False,
            user_category="FACULTY",
            personnel=None,
            department="IT",
            course="BSIT",
            section="A",
        )
        student = SimpleNamespace(
            is_admin=False,
            user_category="COLLEGE_STUDENT",
            personnel=None,
            department="IT",
            course=None,
            section=None,
        )

        self.assertEqual(format_user_role_label(faculty), "Faculty")
        self.assertEqual(format_user_role_label(student), "Student")

    def test_all_active_item_detail_modals_show_one_role_label(self):
        templates = (
            ROOT / "templates" / "Admin Pages" / "Lost_item_Report.html",
            ROOT / "templates" / "Admin Pages" / "Found_item_Report.html",
            ROOT / "templates" / "Student Pages" / "Student_LostReport.html",
            ROOT / "templates" / "Student Pages" / "Student_FoundReport.html",
        )
        for template in templates:
            content = template.read_text(encoding="utf-8")
            with self.subTest(template=template.name):
                self.assertIn("<strong>Role:</strong>", content)
                self.assertNotIn("<strong>Uploader Role:</strong>", content)

        admin_lost = templates[0].read_text(encoding="utf-8")
        self.assertEqual(admin_lost.count("<strong>Role:</strong>"), 1)
        self.assertNotIn('id="modalUploaderRole"', admin_lost)
        self.assertIn("item.report_owner_role || 'Unknown'", admin_lost)

        for template in templates[1:]:
            content = template.read_text(encoding="utf-8")
            with self.subTest(role_source=template.name):
                self.assertIn('id="modalUploaderRole"', content)
                self.assertIn("item.uploader_role || 'Unknown'", content)

    def test_report_owner_role_uses_teacher_and_student_labels(self):
        faculty = SimpleNamespace(
            is_admin=False,
            user_category="FACULTY",
            personnel=None,
            department="IT",
            course=None,
            section=None,
        )
        student = SimpleNamespace(
            is_admin=False,
            user_category="COLLEGE_STUDENT",
            personnel=None,
            department="IT",
            course="BSHM",
            section="1Y1",
        )

        self.assertEqual(format_report_owner_role_label(faculty), "Teacher")
        self.assertEqual(format_report_owner_role_label(student), "Student")
        self.assertEqual(format_report_owner_role_label(None, "BSHM"), "Student")

        lost_template = (
            ROOT / "templates" / "Admin Pages" / "Lost_item_Report.html"
        ).read_text(encoding="utf-8")
        self.assertIn('<strong>Role:</strong> <span id="modalOwnerRole">', lost_template)
        self.assertIn("item.report_owner_role || 'Unknown'", lost_template)
        self.assertNotIn('<strong>Strand / Role:</strong>', lost_template)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date
from types import SimpleNamespace

from pydantic import ValidationError

from admin_routes import (
    AcademicArchiveRequest,
    AcademicSchedulesUpdate,
    UnifiedUserCreate,
    get_following_school_year,
    serialize_academic_term_setting,
)


class UnifiedUserRequestTests(unittest.TestCase):
    def valid_student(self, **overrides):
        payload = {
            "user_category": "COLLEGE_STUDENT",
            "student_no": "2026-000001",
            "first_name": "Ana",
            "middle_name": "",
            "last_name": "Santos",
            "email": "ana.santos@example.edu",
            "program": "BSIT",
            "level": "1st Year",
            "permissions": ["Dashboard"],
        }
        payload.update(overrides)
        return payload

    def test_student_role_controls_permissions_and_level(self):
        request = UnifiedUserCreate(**self.valid_student())
        self.assertEqual(request.permissions, ["Student-Portal-Access"])
        self.assertEqual(request.level, "1st Year")

    def test_compact_tertiary_level_is_saved_as_year(self):
        request = UnifiedUserCreate(**self.valid_student(level="2Y1"))
        self.assertEqual(request.level, "2nd Year")

    def test_whitespace_only_required_value_is_rejected(self):
        with self.assertRaises(ValidationError):
            UnifiedUserCreate(**self.valid_student(first_name="   "))

    def test_bad_email_and_category_level_combination_are_rejected(self):
        with self.assertRaises(ValidationError):
            UnifiedUserCreate(**self.valid_student(email="not-an-email"))
        with self.assertRaises(ValidationError):
            UnifiedUserCreate(**self.valid_student(
                user_category="SHS_STUDENT",
                level="2nd Year",
            ))

    def test_password_complexity_is_enforced_when_supplied(self):
        with self.assertRaises(ValidationError):
            UnifiedUserCreate(**self.valid_student(password="weakpass"))
        request = UnifiedUserCreate(**self.valid_student(password="StrongPass1"))
        self.assertEqual(request.password, "StrongPass1")


class AcademicArchiveRequestTests(unittest.TestCase):
    def test_archive_scope_validation(self):
        request = AcademicArchiveRequest(
            academic_classification="TERTIARY",
            academic_year="2026-2027",
            term_label="First Semester",
        )
        self.assertEqual(request.term_label, "First Semester")
        with self.assertRaises(ValidationError):
            AcademicArchiveRequest(
                academic_classification="SHS",
                academic_year="2026-2028",
                term_label="First Semester",
            )


class AcademicScheduleSeparationTests(unittest.TestCase):
    def test_combined_schedule_has_distinct_tertiary_and_shs_sections(self):
        request = AcademicSchedulesUpdate(
            tertiary={
                "current_academic_year": "2026-2027",
                "current_semester": "1st Semester",
                "current_start_date": "2026-07-28",
                "current_end_date": "2026-12-05",
                "next_academic_year": "2026-2027",
                "next_semester": "2nd Semester",
                "next_start_date": "2027-01-05",
                "next_end_date": "2027-06-05",
            },
            shs={
                "current_academic_year": "2026-2027",
                "current_start_date": "2026-06-15",
                "current_end_date": "2027-03-31",
                "next_academic_year": "2027-2028",
                "next_start_date": "2027-06-14",
                "next_end_date": "2028-03-31",
            },
        )
        self.assertEqual(request.tertiary.current_semester, "1st Semester")
        self.assertEqual(request.shs.current_academic_year, "2026-2027")
        self.assertEqual(get_following_school_year("2026-2027"), "2027-2028")

    def test_serialization_preserves_flat_tertiary_compatibility(self):
        setting = SimpleNamespace(
            current_academic_year="2026-2027",
            current_semester="1st Semester",
            current_start_date=date(2026, 7, 28),
            current_end_date=date(2026, 12, 5),
            current_status="active",
            next_academic_year="2026-2027",
            next_semester="2nd Semester",
            next_start_date=date(2027, 1, 5),
            next_end_date=date(2027, 6, 5),
            shs_current_academic_year="2026-2027",
            shs_current_start_date=date(2026, 6, 15),
            shs_current_end_date=date(2027, 3, 31),
            shs_current_status="active",
            shs_next_academic_year="2027-2028",
            shs_next_start_date=date(2027, 6, 14),
            shs_next_end_date=date(2028, 3, 31),
        )
        result = serialize_academic_term_setting(setting)
        self.assertEqual(result["current_semester"], "1st Semester")
        self.assertEqual(result["tertiary"]["current_semester"], "1st Semester")
        self.assertEqual(result["shs"]["current_term"], "School Year")
        self.assertEqual(result["shs"]["current_end_date"], "2027-03-31")


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

import models
from main import PAGE_ALIASES, build_auth_response, get_user_role_label, portal_root_for_user
from student_routes import get_student_recent_activity


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows_by_model):
        self.rows_by_model = rows_by_model

    def query(self, model):
        return FakeQuery(list(self.rows_by_model.get(model, [])))


class StudentRecentActivityTests(unittest.TestCase):
    @staticmethod
    def faculty_user(**overrides):
        values = {
            "id": 8,
            "email": "faculty@example.com",
            "is_admin": False,
            "must_change_password": False,
            "user_category": "FACULTY",
            "personnel": "Faculty",
            "department": "School of IT",
            "course": None,
            "section": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_recent_activity_uses_real_user_events_in_newest_first_order(self):
        now = datetime.now()
        lost_item = SimpleNamespace(
            id=11,
            status="lost",
            item_name="Black Wallet",
            created_at=now - timedelta(hours=2),
        )
        claim = SimpleNamespace(
            id=31,
            status="approved",
            found_item=SimpleNamespace(item_name="Black Wallet"),
            lost_item=lost_item,
            lost_item_id=11,
            created_at=now - timedelta(hours=1),
            admin_decision_date=now,
        )
        notification = SimpleNamespace(
            id=41,
            type="student_update",
            message="Your profile was updated.",
            created_at=now - timedelta(minutes=30),
            target_url="/student/profile",
        )
        pending_found = SimpleNamespace(
            id=21,
            item_name="Umbrella",
            created_at=now - timedelta(hours=3),
        )
        db = FakeSession({
            models.Notification: [notification],
            models.Item: [lost_item],
            models.PendingItem: [pending_found],
            models.Claim: [claim],
        })

        activities = get_student_recent_activity(
            db=db,
            current_user=SimpleNamespace(id=7),
        )

        self.assertEqual(activities[0]["type"], "claim_approved")
        self.assertEqual(activities[1]["message"], "Your profile was updated.")
        self.assertIn("Black Wallet", activities[2]["message"])
        self.assertTrue(activities[0]["occurred_at"].endswith("Z"))

    def test_faculty_category_is_authoritative_for_role_label(self):
        faculty = self.faculty_user(
            personnel=None,
            course="BSIT",
            section="Faculty Section",
        )

        self.assertEqual(get_user_role_label(faculty), "Faculty")

    def test_faculty_has_separate_page_root_and_login_claim(self):
        faculty = self.faculty_user()
        required_pages = {"dashboard", "Messages", "Lost-report", "Found-report", "profile", "settings"}

        self.assertEqual(portal_root_for_user(faculty), "/faculty")
        self.assertTrue(all(f"/faculty/{page}" in PAGE_ALIASES for page in required_pages))

        response = build_auth_response(faculty)
        payload = json.loads(response.body)
        self.assertEqual(payload["user_category"], "FACULTY")
        self.assertEqual(payload["role_label"], "Faculty")

    def test_personnel_field_supports_legacy_faculty_accounts(self):
        faculty = SimpleNamespace(
            is_admin=False,
            user_category=None,
            personnel="Faculty",
            department=None,
            course="BSIT",
            section="A",
        )

        self.assertEqual(get_user_role_label(faculty), "Faculty")


if __name__ == "__main__":
    unittest.main()

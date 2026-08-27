import unittest

from admin_routes import router as admin_router
from lookfor_constants import (
    IDENTIFIER_RE,
    NAME_RE,
    academic_archive_batch_id,
    classification_for_category,
    display_claim_status,
    infer_legacy_classification,
    normalize_level,
    tertiary_term_for_level,
    normalize_user_category,
    valid_levels_for_category,
)
from lookfor_permissions import (
    ADMIN_PERMISSION_KEYS,
    DEFAULT_ADMIN_PERMISSION_KEYS,
    has_permission,
    normalize_permissions,
    permission_groups_payload,
    permission_response_values,
)


class UserValidationRuleTests(unittest.TestCase):
    def test_categories_and_classifications_are_normalized(self):
        self.assertEqual(normalize_user_category("Senior High School"), "SHS_STUDENT")
        self.assertEqual(normalize_user_category("tertiary"), "COLLEGE_STUDENT")
        self.assertEqual(classification_for_category("faculty"), "NON_ACADEMIC")
        self.assertIsNone(normalize_user_category("superuser"))

    def test_level_combinations_are_controlled(self):
        self.assertEqual(normalize_level("first year"), "1st Year")
        self.assertEqual(normalize_level("1Y1"), "1st Year")
        self.assertEqual(normalize_level("2y1"), "2nd Year")
        self.assertEqual(normalize_level("3Y2"), "3rd Year")
        self.assertEqual(normalize_level("4 Y 1"), "4th Year")
        self.assertIn("Grade 12", valid_levels_for_category("SHS_STUDENT"))
        self.assertNotIn("Grade 12", valid_levels_for_category("COLLEGE_STUDENT"))
        self.assertEqual(valid_levels_for_category("STAFF"), ())

    def test_compact_tertiary_levels_preserve_their_semester(self):
        second_semester_levels = {
            "1Y2": "1st Year",
            "2y2": "2nd Year",
            "3 Y 2": "3rd Year",
            "4Y2": "4th Year",
        }
        for level, expected_year in second_semester_levels.items():
            self.assertEqual(tertiary_term_for_level(level), "Second Semester")
            self.assertEqual(normalize_level(level), expected_year)
        for level in ("1Y1", "2y1", "3 Y 1", "4Y1"):
            self.assertEqual(tertiary_term_for_level(level), "First Semester")
        self.assertIsNone(tertiary_term_for_level("2nd Year"))

    def test_name_and_identifier_rules(self):
        self.assertTrue(NAME_RE.fullmatch("María O'Neil-Santos"))
        self.assertFalse(NAME_RE.fullmatch("User_123"))
        self.assertTrue(IDENTIFIER_RE.fullmatch("EMP-2026.001"))
        self.assertFalse(IDENTIFIER_RE.fullmatch("EMP 001"))


class AcademicArchiveRuleTests(unittest.TestCase):
    def test_shs_and_tertiary_batch_scopes_are_distinct(self):
        self.assertEqual(
            academic_archive_batch_id("SHS", "2026-2027", "School Year"),
            "BATCH-2026-2027 School Year",
        )
        self.assertEqual(
            academic_archive_batch_id("TERTIARY", "2026-2027", "First Semester"),
            "BATCH-2026-2027 1st Semester",
        )
        with self.assertRaises(ValueError):
            academic_archive_batch_id("SHS", "2026-2027", "First Semester")

    def test_ambiguous_legacy_accounts_are_flagged(self):
        category, classification, review = infer_legacy_classification(
            is_admin=False,
            personnel=None,
            department=None,
            course="BSIT",
            section=None,
            level=None,
        )
        self.assertIsNone(category)
        self.assertIsNone(classification)
        self.assertTrue(review)

    def test_reliable_shs_level_is_backfilled(self):
        self.assertEqual(
            infer_legacy_classification(
                is_admin=False,
                personnel=None,
                department=None,
                course="STEM",
                section="A",
                level="Grade 11",
            ),
            ("SHS_STUDENT", "SHS", False),
        )


class StatusMappingTests(unittest.TestCase):
    def test_all_legacy_claimed_values_share_one_label(self):
        for status in ("claimed", "approved", "completed"):
            self.assertEqual(display_claim_status(status), "Claimed Item")
        self.assertEqual(display_claim_status("pending_surrender"), "Pending Surrender")


class GroupedPermissionTests(unittest.TestCase):
    @staticmethod
    def route_permission(path, method):
        route = next(
            route for route in admin_router.routes
            if route.path == path and method in route.methods
        )
        return {
            getattr(dependency.call, "required_permission", None)
            for dependency in route.dependant.dependencies
        } - {None}

    def test_settings_is_not_configurable(self):
        self.assertFalse(any(key == "settings" or key.startswith("settings.") for key in ADMIN_PERMISSION_KEYS))
        payload_keys = {
            action["key"]
            for group in permission_groups_payload()
            for action in group["actions"]
        }
        self.assertNotIn("settings.view", payload_keys)

    def test_profile_and_notifications_are_implicit_not_configurable(self):
        payload_keys = {
            action["key"]
            for group in permission_groups_payload()
            for action in group["actions"]
        }
        self.assertTrue(set(DEFAULT_ADMIN_PERMISSION_KEYS).isdisjoint(payload_keys))
        self.assertTrue(set(DEFAULT_ADMIN_PERMISSION_KEYS).isdisjoint(ADMIN_PERMISSION_KEYS))
        self.assertTrue(
            set(DEFAULT_ADMIN_PERMISSION_KEYS).issubset(
                permission_response_values(["dashboard.view"])
            )
        )
        self.assertNotIn(
            "profile.view",
            normalize_permissions(["dashboard.view", "profile.view"]),
        )

    def test_legacy_permissions_expand_to_canonical_actions(self):
        permissions = normalize_permissions(["User-Management-Edit", "Content-management-Term"])
        self.assertIn("user_management.edit", permissions)
        self.assertIn("user_management.view", permissions)
        self.assertIn("academic_term.manage", permissions)
        self.assertIn("academic_archiving.execute", permissions)

    def test_actions_include_required_module_view(self):
        permissions = normalize_permissions(["messages.send", "announcements.publish"])
        self.assertIn("messages.view", permissions)
        self.assertIn("content_management.view", permissions)
        self.assertTrue(has_permission(permissions, "messages.send"))
        self.assertFalse(has_permission(permissions, "messages.manage"))

    def test_sensitive_routes_use_their_specific_actions(self):
        expectations = {
            ("/admin/dashboard-stats", "GET"): "dashboard.view",
            ("/admin/users", "GET"): "user_management.view",
            ("/admin/items/lost", "POST"): "lost_items.create",
            ("/admin/approve-item/{item_id}", "POST"): "found_items.approve",
            ("/admin/academic-archives/execute", "POST"): "academic_archiving.execute",
            ("/admin/notifications/mark-all-read", "POST"): "notifications.manage",
        }
        for (path, method), permission in expectations.items():
            with self.subTest(path=path, method=method):
                self.assertEqual(self.route_permission(path, method), {permission})

    def test_settings_route_did_not_receive_configurable_permission(self):
        self.assertEqual(self.route_permission("/admin/update-settings", "POST"), set())


if __name__ == "__main__":
    unittest.main()

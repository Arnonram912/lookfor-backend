import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from models import SettingsUpdate
from main import logout_other_sessions
from security import resolve_authenticated_user


ROOT = Path(__file__).resolve().parents[1]


class FakeQuery:
    def __init__(self, user):
        self.user = user

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.user


class FakeDB:
    def __init__(self, user):
        self.user = user

    def query(self, *args, **kwargs):
        return FakeQuery(self.user)

    def commit(self):
        pass

    def refresh(self, value):
        pass


class CompletedSettingsTests(unittest.TestCase):
    def test_settings_payload_supports_sound_theme_and_defaults(self):
        settings = SettingsUpdate(
            two_factor=False,
            notifications=True,
            theme="dark",
            font_size=18,
            notification_sound="mute",
        )
        self.assertEqual(settings.theme, "dark")
        self.assertEqual(settings.notification_sound, "mute")

    @patch("security.jwt.decode")
    def test_rotated_session_rejects_an_old_token(self, decode):
        decode.return_value = {"sub": "user@example.com", "id": 7, "session_version": 2}
        user = SimpleNamespace(
            id=7,
            email="user@example.com",
            is_archived=False,
            session_version=3,
        )

        with self.assertRaises(HTTPException) as raised:
            resolve_authenticated_user("old-token", FakeDB(user))

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail, "Session was signed out")

    @patch("security.jwt.decode")
    def test_legacy_token_remains_valid_before_first_rotation(self, decode):
        decode.return_value = {"sub": "user@example.com", "id": 7}
        user = SimpleNamespace(
            id=7,
            email="user@example.com",
            is_archived=False,
            session_version=0,
        )

        self.assertIs(resolve_authenticated_user("legacy-token", FakeDB(user)), user)

    def test_admin_and_student_pages_wire_every_visible_control(self):
        for relative_path in (
            "templates/Admin Pages/Setting.html",
            "templates/Student Pages/Student_Settings.html",
        ):
            html = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn('id="theme-select"', html)
            self.assertIn("notification_sound:", html)
            self.assertIn("onclick=\"resetSettings()\"", html)
            self.assertIn("logoutOtherSessions(this)", html)
            self.assertIn("/auth/logout-other-sessions", html)

    def test_shared_portal_script_applies_and_alerts_preferences(self):
        script = (ROOT / "static/session-keepalive.js").read_text(encoding="utf-8")
        self.assertIn("syncUserPreferences()", script)
        self.assertIn("lookfor-dark-theme", script)
        self.assertIn('lookfor:new-notifications', script)
        self.assertIn("playNotificationTone", script)

    @patch("main.create_access_token", return_value="replacement-token")
    def test_logout_other_sessions_rotates_generation_and_returns_current_token(self, create_token):
        user = SimpleNamespace(
            id=7,
            email="user@example.com",
            is_admin=False,
            user_category="COLLEGE_STUDENT",
            personnel=None,
            must_change_password=False,
            session_version=4,
        )

        response = logout_other_sessions(db=FakeDB(user), current_user=user)

        self.assertEqual(user.session_version, 5)
        self.assertIn(b'"access_token":"replacement-token"', response.body)
        self.assertEqual(create_token.call_args.kwargs["data"]["session_version"], 5)


if __name__ == "__main__":
    unittest.main()

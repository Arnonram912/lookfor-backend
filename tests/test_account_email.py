import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from account_email import (
    POSSIBLE_MATCH_EMAIL_TEXT,
    _finish_account_email,
    build_account_access_messages,
    send_account_access_email_stage,
    send_item_event_email,
)


class FakeOutboxQuery:
    def __init__(self, job):
        self.job = job

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.job


class FakeOutboxSession:
    def __init__(self, job):
        self.job = job
        self.committed = False

    def query(self, *args, **kwargs):
        return FakeOutboxQuery(self.job)

    def add(self, value):
        pass

    def commit(self):
        self.committed = True

    def close(self):
        pass


class AccountEmailTests(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {"GMAIL_SENDER_EMAIL": "lookfor@example.com", "GMAIL_APP_PASSWORD": "app-password"},
    )
    @patch("account_email.smtplib.SMTP_SSL")
    def test_possible_match_disclaimer_is_italicized_in_html_only(self, smtp_ssl):
        smtp = MagicMock()
        smtp_ssl.return_value.__enter__.return_value = smtp

        send_item_event_email(
            "student@example.com",
            "Alex Student",
            subject="A possible match was found for your lost item",
            message_text=POSSIBLE_MATCH_EMAIL_TEXT,
        )

        message = smtp.send_message.call_args.args[0]
        plain_body = message.get_body(preferencelist=("plain",)).get_content()
        html_body = message.get_body(preferencelist=("html",)).get_content()

        self.assertIn("Disclaimer: This system is using an AI.", plain_body)
        self.assertIn(
            "<p><em>Disclaimer: This system is using an AI.",
            html_body,
        )
        self.assertIn("before completing a claim.</em></p>", html_body)
        self.assertNotIn("<em>Good news!", html_body)

    def test_account_credentials_are_split_between_two_messages(self):
        username_message, password_message = build_account_access_messages(
            "student@example.com",
            "Alex Student",
            "Temp-Secret-123",
            sender_email="lookfor@example.com",
            login_url="https://lookfor.example.com/login",
        )

        username_body = username_message.get_body(preferencelist=("plain",)).get_content()
        password_body = password_message.get_body(preferencelist=("plain",)).get_content()

        self.assertEqual(username_message["Subject"], "Your LookFor Account Has Been Created")
        self.assertIn("Username: student@example.com", username_body)
        self.assertIn("temporary password provided in the separate email", username_body)
        self.assertNotIn("Temp-Secret-123", username_body)

        self.assertEqual(password_message["Subject"], "Your LookFor Temporary Password")
        self.assertIn("Temporary Password: Temp-Secret-123", password_body)
        self.assertNotIn("Username: student@example.com", password_body)

    @patch.dict(
        "os.environ",
        {"GMAIL_SENDER_EMAIL": "lookfor@example.com", "GMAIL_APP_PASSWORD": "app-password"},
    )
    @patch("account_email.smtplib.SMTP_SSL")
    def test_stage_sender_sends_only_requested_message(self, smtp_ssl):
        smtp = MagicMock()
        smtp_ssl.return_value.__enter__.return_value = smtp

        send_account_access_email_stage(
            "student@example.com",
            "Alex Student",
            "Temp-Secret-123",
            stage="username",
        )

        smtp.send_message.assert_called_once()
        self.assertEqual(
            smtp.send_message.call_args.args[0]["Subject"],
            "Your LookFor Account Has Been Created",
        )

    @patch("account_email._PASSWORD_EMAIL_DELAY_MINUTES", 2)
    def test_successful_username_email_schedules_password_two_minutes_later(self):
        before = datetime.utcnow()
        job = SimpleNamespace(
            id=7,
            status="sending_username",
            attempt_count=1,
            available_at=before,
            sent_at=None,
            last_error=None,
            recipient_email="student@example.com",
        )
        db = FakeOutboxSession(job)

        with patch("account_email.SessionLocal", return_value=db):
            _finish_account_email(job.id, stage="username")

        delay_seconds = (job.available_at - before).total_seconds()
        self.assertEqual(job.status, "password_pending")
        self.assertEqual(job.attempt_count, 0)
        self.assertGreaterEqual(delay_seconds, 120)
        self.assertLess(delay_seconds, 121)
        self.assertIsNone(job.sent_at)
        self.assertTrue(db.committed)


if __name__ == "__main__":
    unittest.main()

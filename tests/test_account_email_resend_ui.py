import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class AccountEmailResendUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = (ROOT / "templates" / "Admin Pages" / "User_Management.html").read_text(
            encoding="utf-8"
        )
        cls.routes = (ROOT / "admin_routes.py").read_text(encoding="utf-8")
        cls.email_worker = (ROOT / "account_email.py").read_text(encoding="utf-8")

    def test_delivery_status_is_not_rendered_in_user_tables(self):
        self.assertNotIn("<th>Email Status</th>", self.template)
        self.assertNotIn("const emailStatusColumn", self.template)
        self.assertNotIn("resendCredentialEmail(${user.id}, this)", self.template)

    def test_profile_view_shows_delivery_status_and_failed_resend_action(self):
        self.assertIn('id="profileViewEmailDeliveryStatus"', self.template)
        self.assertIn('id="profileResendEmailBtn"', self.template)
        self.assertIn("normalizedStatus === 'failed'", self.template)
        self.assertIn("renderProfileEmailDelivery(user)", self.template)

    def test_resend_reuses_failed_job_without_creating_an_account(self):
        self.assertIn('@router.post("/users/{user_id}/credential-email/resend")', self.routes)
        self.assertIn('failed_status not in {"failed", "failed_username", "failed_password"}', self.routes)
        self.assertIn('failed_status == "failed_password" else "pending"', self.routes)
        self.assertIn('email_job.attempt_count = 0', self.routes)

    def test_resend_all_retries_only_each_recipients_latest_failed_job(self):
        self.assertIn('@router.post("/users/credential-emails/resend-all")', self.routes)
        bulk_route = self.routes.split(
            '@router.post("/users/credential-emails/resend-all")', 1
        )[1].split('# --- 8. AI & UPLOAD ROUTES ---', 1)[0]
        self.assertIn('func.max(models.AccountEmailOutbox.id)', bulk_route)
        self.assertIn('.group_by(func.lower(models.AccountEmailOutbox.recipient_email))', bulk_route)
        self.assertIn('{"failed", "failed_username", "failed_password"}', bulk_route)
        self.assertIn('models.User.is_archived == False', bulk_route)
        self.assertIn('"queued_count": queued_count', bulk_route)
        self.assertIn('id="resendAllCredentialEmailsBtn"', self.template)
        self.assertIn("fetch('/admin/users/credential-emails/resend-all'", self.template)
        self.assertIn('reverseButtons: true', self.template)

    def test_permanent_delivery_failure_creates_admin_notification(self):
        self.assertIn('type="account_email_failed"', self.email_worker)
        self.assertIn('target_url="/admin/User-Management"', self.email_worker)

    def test_password_reset_queues_the_new_credentials(self):
        reset_route = self.routes.split('@router.post("/reset-student-password")', 1)[1].split(
            'import os', 1
        )[0]
        self.assertIn('queue_account_access_email(', reset_route)
        self.assertIn('new_temp,', reset_route)
        self.assertIn('supersede_existing=True', reset_route)
        self.assertIn('"email_queued": email_queued', reset_route)
        self.assertIn('id="resetResultDelivery"', self.template)
        self.assertIn(
            'showResetPasswordResult(email, result.new_temp_password, result.email_queued)',
            self.template,
        )


if __name__ == "__main__":
    unittest.main()

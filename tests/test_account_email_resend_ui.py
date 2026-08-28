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

    def test_permanent_delivery_failure_creates_admin_notification(self):
        self.assertIn('type="account_email_failed"', self.email_worker)
        self.assertIn('target_url="/admin/User-Management"', self.email_worker)


if __name__ == "__main__":
    unittest.main()

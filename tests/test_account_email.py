import unittest

from account_email import build_account_access_messages


class AccountEmailTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

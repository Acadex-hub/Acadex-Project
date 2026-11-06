import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from js import app as backend


class PasswordResetEmailTest(unittest.TestCase):
    def setUp(self):
        backend.app.config.update(TESTING=True, SECRET_KEY="password-reset-test-secret")
        self.client = backend.app.test_client()
        self.connection = MagicMock()
        self.cursor = MagicMock()
        self.connection.cursor.return_value = self.cursor
        self.cursor.fetchone.side_effect = [
            {"user_id": 12, "email": "student@example.com"},
            None,
        ]
        self.database = patch.object(
            backend,
            "database_connection",
            side_effect=lambda: nullcontext(self.connection),
        )
        self.database.start()
        self.addCleanup(self.database.stop)

    def test_missing_smtp_settings_are_reported_and_code_is_invalidated(self):
        with patch.object(
            backend,
            "send_otp_email",
            side_effect=RuntimeError("Set SMTP_HOST in .env to enable password reset email."),
        ):
            response = self.client.post(
                "/api/forgot-password",
                json={"email": "student@example.com"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json()["message"],
            "Set SMTP_HOST in .env to enable password reset email.",
        )
        throttle_query = self.cursor.execute.call_args_list[1].args[0]
        self.assertIn("used_at IS NULL", throttle_query)
        self.assertEqual(self.cursor.execute.call_count, 5)
        self.assertIn(
            "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP",
            self.cursor.execute.call_args_list[-1].args[0],
        )
        self.assertEqual(self.connection.commit.call_count, 2)

    def test_invalid_smtp_settings_are_reported_and_code_is_invalidated(self):
        with patch.object(backend, "send_otp_email", side_effect=ValueError("invalid port")):
            response = self.client.post(
                "/api/forgot-password",
                json={"email": "student@example.com"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("Check SMTP_HOST, SMTP_PORT", response.get_json()["message"])
        throttle_query = self.cursor.execute.call_args_list[1].args[0]
        self.assertIn("used_at IS NULL", throttle_query)
        self.assertEqual(self.cursor.execute.call_count, 5)
        self.assertEqual(self.connection.commit.call_count, 2)

    def test_smtp_connection_timeout_explains_network_block(self):
        with patch.object(backend, "send_otp_email", side_effect=TimeoutError):
            response = self.client.post(
                "/api/forgot-password",
                json={"email": "student@example.com"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("network or firewall", response.get_json()["message"])
        self.assertEqual(self.cursor.execute.call_count, 5)
        self.assertEqual(self.connection.commit.call_count, 2)

    def test_smtp_authentication_rejection_explains_credentials(self):
        with patch.object(
            backend,
            "send_otp_email",
            side_effect=backend.smtplib.SMTPAuthenticationError(535, b"Authentication failed"),
        ):
            response = self.client.post(
                "/api/forgot-password",
                json={"email": "student@example.com"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("provider rejected SMTP login", response.get_json()["message"])
        self.assertEqual(self.cursor.execute.call_count, 5)
        self.assertEqual(self.connection.commit.call_count, 2)

    def test_smtp_disconnect_has_specific_actionable_message(self):
        with patch.object(
            backend,
            "send_otp_email",
            side_effect=backend.smtplib.SMTPServerDisconnected("connection unexpectedly closed"),
        ):
            response = self.client.post(
                "/api/forgot-password",
                json={"email": "student@example.com"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("closed the connection during login or delivery", response.get_json()["message"])
        self.assertEqual(self.cursor.execute.call_count, 5)
        self.assertEqual(self.connection.commit.call_count, 2)


if __name__ == "__main__":
    unittest.main()

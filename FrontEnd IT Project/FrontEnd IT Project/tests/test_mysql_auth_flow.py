import secrets
import unittest
from unittest.mock import patch

import app as backend


class MysqlAuthFlowTest(unittest.TestCase):
    def setUp(self):
        backend.app.config.update(TESTING=True, SECRET_KEY="integration-test-secret")
        self.client = backend.app.test_client()
        self.email = f"copilot-auth-check-{secrets.token_hex(6)}@example.invalid"
        self.account_created = False

    def tearDown(self):
        if self.account_created:
            with backend.database_connection() as connection:
                cursor = connection.cursor()
                cursor.execute("DELETE FROM users WHERE email = %s", (self.email,))
                connection.commit()
                cursor.close()

    def test_signup_login_and_email_otp_password_reset(self):
        original_password = "Initial-password-123"
        replacement_password = "Changed-password-456"
        signup = self.client.post(
            "/api/signup",
            json={
                "full_name": "Temporary Integration User",
                "email": self.email,
                "password": original_password,
            },
        )
        self.assertEqual(signup.status_code, 201, signup.get_json())
        self.account_created = True

        login = self.client.post(
            "/api/login",
            json={"email": self.email, "password": original_password, "admin": False},
        )
        self.assertEqual(login.status_code, 200, login.get_json())
        self.assertEqual(login.get_json()["role"], "student")
        current_profile = self.client.get("/api/me")
        self.assertEqual(current_profile.status_code, 200)
        self.assertEqual(current_profile.get_json()["email"], self.email)
        self.assertEqual(current_profile.get_json()["full_name"], "Temporary Integration User")
        self.assertNotIn("password", current_profile.get_json())

        profile_update = self.client.put(
            "/api/profile",
            json={
                "full_name": "Updated Integration User",
                "institution": "Test Campus",
                "course_of_study": "Software Engineering",
                "year_of_study": "3",
                "bio": "Profile persisted in MySQL.",
            },
        )
        self.assertEqual(profile_update.status_code, 200, profile_update.get_json())
        refreshed_profile = self.client.get("/api/me").get_json()
        self.assertEqual(refreshed_profile["full_name"], "Updated Integration User")
        self.assertEqual(refreshed_profile["institution"], "Test Campus")
        self.assertEqual(refreshed_profile["course_of_study"], "Software Engineering")
        self.assertEqual(refreshed_profile["year_of_study"], 3)
        self.assertEqual(refreshed_profile["bio"], "Profile persisted in MySQL.")

        sent_codes = []
        with patch.object(backend, "send_otp_email", side_effect=lambda recipient, otp: sent_codes.append((recipient, otp))):
            requested = self.client.post("/api/forgot-password", json={"email": self.email})
        self.assertEqual(requested.status_code, 200, requested.get_json())
        self.assertEqual(len(sent_codes), 1)
        self.assertEqual(sent_codes[0][0], self.email)
        otp = sent_codes[0][1]
        self.assertEqual(len(otp), 6)
        self.assertTrue(otp.isdigit())

        unverified_reset = self.client.post(
            "/api/reset-password",
            json={"email": self.email, "password": replacement_password},
        )
        self.assertEqual(unverified_reset.status_code, 403)

        wrong_otp = "000000" if otp != "000000" else "000001"
        rejected = self.client.post(
            "/api/verify-reset-otp",
            json={"email": self.email, "otp": wrong_otp, "password": replacement_password},
        )
        self.assertEqual(rejected.status_code, 400)

        verified = self.client.post(
            "/api/verify-reset-otp",
            json={"email": self.email, "otp": otp},
        )
        self.assertEqual(verified.status_code, 200, verified.get_json())
        reset = self.client.post(
            "/api/reset-password",
            json={"email": self.email, "password": replacement_password},
        )
        self.assertEqual(reset.status_code, 200, reset.get_json())
        self.assertEqual(
            self.client.post(
                "/api/login",
                json={"email": self.email, "password": original_password, "admin": False},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/login",
                json={"email": self.email, "password": replacement_password, "admin": False},
            ).status_code,
            200,
        )
        reused = self.client.post(
            "/api/verify-reset-otp",
            json={"email": self.email, "otp": otp},
        )
        self.assertEqual(reused.status_code, 400)


if __name__ == "__main__":
    unittest.main()

import unittest

import app as backend


class AdminDashboardApiTest(unittest.TestCase):
    def setUp(self):
        backend.app.config.update(TESTING=True, SECRET_KEY="admin-dashboard-test-secret")
        self.client = backend.app.test_client()

    def test_dashboard_data_requires_admin_role(self):
        self.assertEqual(self.client.get("/api/admin/dashboard").status_code, 403)
        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = 1
            browser_session["role"] = "student"
        self.assertEqual(self.client.get("/api/admin/dashboard").status_code, 403)

    def test_dashboard_data_uses_live_database_records(self):
        with backend.database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT u.user_id FROM users AS u "
                    "JOIN user_roles AS ur ON ur.user_id = u.user_id "
                    "JOIN roles AS r ON r.role_id = ur.role_id "
                    "WHERE u.account_status = 'active' AND r.role_key = 'admin' "
                    "ORDER BY u.user_id LIMIT 1"
                )
                admin_user = cursor.fetchone()
            finally:
                cursor.close()

        if not admin_user:
            self.skipTest("An active admin account is required for this integration test.")

        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = admin_user["user_id"]
            browser_session["role"] = "admin"

        response = self.client.get("/api/admin/dashboard")
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertTrue(payload["admin_name"])
        self.assertEqual(
            set(payload["stats"]),
            {"student_count", "resource_count", "course_count", "pending_resource_count"},
        )
        self.assertTrue(all(isinstance(value, int) for value in payload["stats"].values()))
        self.assertTrue(all(item["status"] == "pending" for item in payload["pending_resources"]))
        self.assertLessEqual(len(payload["activity"]), 8)


if __name__ == "__main__":
    unittest.main()

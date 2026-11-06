from contextlib import contextmanager
from datetime import datetime
import unittest
from unittest.mock import patch

from js import app as backend


class FakeAuditCursor:
    def __init__(self, connection):
        self.connection = connection
        self.last_query = ""
        self.lastrowid = connection.lastrowid

    def execute(self, query, parameters=None):
        self.last_query = " ".join(query.split())
        self.connection.queries.append((self.last_query, parameters))

    def fetchone(self):
        if self.last_query.startswith("SELECT u.full_name FROM users"):
            return {"full_name": "Test Admin"} if self.connection.active_admin else None
        if self.last_query.startswith("SELECT role_id FROM roles"):
            return (2,)
        if self.last_query.startswith("SELECT account_status FROM users"):
            return {"account_status": self.connection.account_status}
        if "AS has_student_role" in self.last_query:
            return {"has_student_role": 1, "has_admin_role": 0}
        if self.last_query.startswith("SELECT status FROM resources"):
            return {"status": "pending"}
        return None

    def fetchall(self):
        if "FROM admin_audit_log AS audit" in self.last_query:
            return self.connection.audit_logs
        return []

    def close(self):
        pass


class FakeAuditConnection:
    def __init__(self, audit_logs=None, active_admin=True, account_status="active"):
        self.audit_logs = audit_logs or []
        self.active_admin = active_admin
        self.account_status = account_status
        self.queries = []
        self.committed = False
        self.lastrowid = 246

    def cursor(self, dictionary=False):
        return FakeAuditCursor(self)

    def commit(self):
        self.committed = True

    def close(self):
        pass


class AdminAuditLogTest(unittest.TestCase):
    def setUp(self):
        backend.app.config.update(TESTING=True, SECRET_KEY="admin-audit-test-secret")
        self.client = backend.app.test_client()

    def login_as_admin(self):
        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = 42
            browser_session["role"] = "admin"

    def database_connection_for(self, connection):
        @contextmanager
        def fake_database_connection():
            yield connection

        return fake_database_connection

    def test_resource_review_writes_audit_record_in_same_transaction(self):
        self.login_as_admin()
        connection = FakeAuditConnection()
        with patch.object(backend, "database_connection", self.database_connection_for(connection)):
            response = self.client.post(
                "/api/admin/resources/91/review",
                json={"status": "approved"},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(connection.committed)
        audit_insert = next(
            (query, parameters)
            for query, parameters in connection.queries
            if query.startswith("INSERT INTO admin_audit_log")
        )
        self.assertEqual(
            audit_insert[1],
            (42, "resource.approved", "resource", 91, "Resource review status set to approved."),
        )

    def test_admin_can_list_recent_audit_records(self):
        self.login_as_admin()
        entries = [
            {
                "audit_id": 7,
                "admin_user_id": 42,
                "admin_name": "Test Admin",
                "action": "resource.rejected",
                "target_type": "resource",
                "target_id": 91,
                "details": "Resource review status set to rejected.",
                "created_at": datetime(2026, 10, 31, 12, 0, 0),
            }
        ]
        connection = FakeAuditConnection(audit_logs=entries)
        with patch.object(backend, "database_connection", self.database_connection_for(connection)):
            response = self.client.get("/api/admin/audit-logs?limit=25")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["audit_logs"][0]["action"], "resource.rejected")
        self.assertEqual(response.get_json()["audit_logs"][0]["target_id"], 91)
        audit_query = next(
            (query, parameters)
            for query, parameters in connection.queries
            if "FROM admin_audit_log AS audit" in query
        )
        self.assertEqual(audit_query[1], (25,))
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_audit_log_requires_admin_and_valid_limit(self):
        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = 42
            browser_session["role"] = "student"
        self.assertEqual(self.client.get("/api/admin/audit-logs").status_code, 403)

        self.login_as_admin()
        self.assertEqual(self.client.get("/api/admin/audit-logs?limit=101").status_code, 400)

    def test_admin_can_create_student_and_audit_it(self):
        self.login_as_admin()
        connection = FakeAuditConnection()
        with patch.object(backend, "database_connection", self.database_connection_for(connection)):
            response = self.client.post(
                "/api/admin/students",
                json={
                    "full_name": "New Student",
                    "email": "new.student@example.com",
                    "password": "initial-password",
                },
            )

        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["user_id"], 246)
        self.assertTrue(connection.committed)
        audit_insert = next(
            (query, parameters)
            for query, parameters in connection.queries
            if query.startswith("INSERT INTO admin_audit_log")
        )
        self.assertEqual(
            audit_insert[1],
            (42, "student.created", "user", 246, "Student account created for new.student@example.com."),
        )
        user_insert = next(
            (query, parameters)
            for query, parameters in connection.queries
            if query.startswith("INSERT INTO users")
        )
        self.assertNotEqual(user_insert[1][1], "initial-password")

    def test_admin_can_deactivate_student_and_audit_it(self):
        self.login_as_admin()
        connection = FakeAuditConnection()
        with patch.object(backend, "database_connection", self.database_connection_for(connection)):
            response = self.client.patch(
                "/api/admin/students/73",
                json={"account_status": "suspended"},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["account_status"], "suspended")
        self.assertTrue(connection.committed)
        audit_insert = next(
            (query, parameters)
            for query, parameters in connection.queries
            if query.startswith("INSERT INTO admin_audit_log")
        )
        self.assertEqual(
            audit_insert[1],
            (42, "student.deactivated", "user", 73, "Student account deactivated; account data retained."),
        )

    def test_admin_can_reactivate_student_and_audit_it(self):
        self.login_as_admin()
        connection = FakeAuditConnection(account_status="suspended")
        with patch.object(backend, "database_connection", self.database_connection_for(connection)):
            response = self.client.patch(
                "/api/admin/students/73",
                json={"account_status": "active"},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["account_status"], "active")
        self.assertTrue(connection.committed)
        status_update = next(
            (query, parameters)
            for query, parameters in connection.queries
            if query.startswith("UPDATE users SET account_status")
        )
        self.assertEqual(status_update[1], ("active", 73, "suspended"))
        audit_insert = next(
            (query, parameters)
            for query, parameters in connection.queries
            if query.startswith("INSERT INTO admin_audit_log")
        )
        self.assertEqual(
            audit_insert[1],
            (
                42,
                "student.reactivated",
                "user",
                73,
                "Student account reactivated; retained account data restored.",
            ),
        )


if __name__ == "__main__":
    unittest.main()

import base64
import json
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import app as backend


class DashboardDataTest(unittest.TestCase):
    @staticmethod
    def encrypted_payload(sender_id=17, recipient_id=25):
        return {
            "v": 1,
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "iv": base64.b64encode(b"i" * 12).decode("ascii"),
            "ciphertext": base64.b64encode(b"c" * 16).decode("ascii"),
            "keys": {
                str(sender_id): base64.b64encode(b"s" * 256).decode("ascii"),
                str(recipient_id): base64.b64encode(b"r" * 256).decode("ascii"),
            },
            "signature": base64.b64encode(b"g" * 64).decode("ascii"),
        }

    @staticmethod
    def public_key_bundle():
        return json.dumps({
            "v": 1,
            "encryption": base64.b64encode(b"e" * 294).decode("ascii"),
            "signing": base64.b64encode(b"s" * 91).decode("ascii"),
        })

    def setUp(self):
        backend.app.config.update(TESTING=True, SECRET_KEY="dashboard-test-secret")
        self.client = backend.app.test_client()
        self.connection = MagicMock()
        self.cursor = MagicMock()
        self.connection.cursor.return_value = self.cursor
        self.database = patch.object(
            backend,
            "database_connection",
            side_effect=lambda: nullcontext(self.connection),
        )
        self.database.start()
        self.addCleanup(self.database.stop)

    def sign_in_as_student(self):
        with self.client.session_transaction() as session:
            session["user_id"] = 17
            session["role"] = "student"

    def sign_in_as_admin(self):
        with self.client.session_transaction() as session:
            session["user_id"] = 1
            session["role"] = "admin"

    def test_resources_endpoint_only_queries_approved_rows(self):
        resource = {
            "resource_id": 8,
            "title": "Approved notes",
            "resource_type": "notes",
            "status": "approved",
        }
        self.cursor.fetchall.return_value = [resource]
        self.sign_in_as_student()

        response = self.client.get("/api/resources")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["resources"], [resource])
        query = self.cursor.execute.call_args.args[0]
        self.assertIn("WHERE r.status = 'approved'", query)

    def test_public_resource_stats_count_only_approved_resources(self):
        self.cursor.fetchone.return_value = {
            "resource_count": 12,
            "notes_count": 7,
            "past_paper_count": 3,
            "it_material_count": 8,
            "ba_material_count": 4,
            "course_count": 2,
        }

        response = self.client.get("/api/resource-stats")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), self.cursor.fetchone.return_value)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        query = self.cursor.execute.call_args.args[0]
        self.assertIn("resource_type = 'notes'", query)
        self.assertIn("resource_type = 'past_paper'", query)
        self.assertIn("resource_category = 'IT'", query)
        self.assertIn("'Business Administration', 'Business Studies'", query)
        self.assertIn("FROM resources WHERE status = 'approved'", query)
        self.assertNotIn("FROM courses WHERE is_active = 1", query)

    def test_student_activity_report_requires_admin(self):
        response = self.client.get("/api/admin/student-activity?month=2026-10")

        self.assertEqual(response.status_code, 403)
        self.cursor.execute.assert_not_called()

    def test_student_activity_report_shows_active_students_and_daily_hours(self):
        self.sign_in_as_admin()
        tracking_start = datetime(2026, 10, 5, 12, 0)
        self.cursor.fetchone.side_effect = [
            {"full_name": "Admin"},
            {"tracking_started_at": tracking_start},
        ]
        self.cursor.fetchall.side_effect = [
            [{
                "user_id": 17,
                "full_name": "Jordan Lee",
                "email": "jordan@example.com",
                "account_status": "active",
            }, {
                "user_id": 18,
                "full_name": "Taylor Smith",
                "email": "taylor@example.com",
                "account_status": "suspended",
            }],
            [
                {
                    "user_id": 17,
                    "started_at": datetime(2026, 10, 5, 23, 0),
                    "session_end": datetime(2026, 10, 6, 1, 0),
                },
                {
                    "user_id": 17,
                    "started_at": datetime(2026, 10, 5, 23, 30),
                    "session_end": datetime(2026, 10, 6, 0, 30),
                },
            ],
        ]

        response = self.client.get("/api/admin/student-activity?month=2026-10")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        students = response.get_json()["students"]
        student = students[0]
        self.assertEqual(student["email"], "jordan@example.com")
        self.assertEqual(student["account_status"], "active")
        self.assertEqual(student["total_hours"], 2.0)
        self.assertEqual(len(student["daily_hours"]), 31)
        self.assertIsNone(student["daily_hours"][3]["hours"])
        self.assertEqual(student["daily_hours"][4]["hours"], 1.0)
        self.assertEqual(student["daily_hours"][5]["hours"], 1.0)
        self.assertEqual(students[1]["account_status"], "suspended")
        self.assertEqual(students[1]["daily_hours"], [])
        student_query = self.cursor.execute.call_args_list[2].args[0]
        self.assertIn("u.account_status IN ('active', 'suspended')", student_query)
        self.assertIn("r.role_key = 'student'", student_query)
        activity_query = self.cursor.execute.call_args_list[3].args[0]
        self.assertIn("u.account_status = 'active'", activity_query)
        self.assertIn("student_login_sessions", activity_query)
        self.assertIn("DATE_ADD(s.last_seen_at", activity_query)

    def test_student_activity_report_rejects_invalid_month(self):
        self.sign_in_as_admin()

        response = self.client.get("/api/admin/student-activity?month=2026-13")

        self.assertEqual(response.status_code, 400)
        self.cursor.execute.assert_not_called()

    def test_student_session_heartbeat_starts_tracking_existing_logins(self):
        self.sign_in_as_student()
        self.cursor.lastrowid = 41

        response = self.client.post("/api/student/session-heartbeat")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json(), {"status": "active"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        with self.client.session_transaction() as session:
            self.assertEqual(session["student_activity_id"], 41)
        self.assertIn(
            "INSERT INTO student_login_sessions",
            self.cursor.execute.call_args.args[0],
        )
        self.connection.commit.assert_called_once()

    def test_student_login_starts_a_tracked_session(self):
        self.cursor.fetchone.return_value = {
            "user_id": 17,
            "email": "jordan@example.com",
            "full_name": "Jordan Lee",
            "password_hash": "hashed-password",
            "account_status": "active",
            "role_keys": "student",
        }
        self.cursor.lastrowid = 41

        with patch.object(backend, "check_password_hash", return_value=True):
            response = self.client.post(
                "/api/login",
                json={"email": "jordan@example.com", "password": "valid-password"},
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn(
            "INSERT INTO student_login_sessions",
            self.cursor.execute.call_args_list[2].args[0],
        )
        with self.client.session_transaction() as session:
            self.assertEqual(session["student_activity_id"], 41)
        self.connection.commit.assert_called_once()

    def test_student_logout_closes_the_tracked_session(self):
        self.sign_in_as_student()
        with self.client.session_transaction() as session:
            session["student_activity_id"] = 41

        response = self.client.post("/api/logout")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn(
            "UPDATE student_login_sessions",
            self.cursor.execute.call_args.args[0],
        )
        self.assertIn("LEAST(CURRENT_TIMESTAMP", self.cursor.execute.call_args.args[0])
        self.connection.commit.assert_called_once()
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_student_session_heartbeat_restarts_after_inactivity_timeout(self):
        self.sign_in_as_student()
        with self.client.session_transaction() as session:
            session["student_activity_id"] = 40
        now = datetime.now()
        self.cursor.fetchone.return_value = {
            "last_seen_at": now - timedelta(minutes=5),
            "ended_at": None,
            "database_now": now,
        }
        self.cursor.lastrowid = 41

        response = self.client.post("/api/student/session-heartbeat")

        self.assertEqual(response.status_code, 200, response.get_json())
        with self.client.session_transaction() as session:
            self.assertEqual(session["student_activity_id"], 41)
        self.assertIn(
            "DATE_ADD(last_seen_at, INTERVAL %s SECOND)",
            self.cursor.execute.call_args_list[1].args[0],
        )
        self.connection.commit.assert_called_once()

    def test_student_search_matches_active_student_usernames(self):
        student = {"user_id": 25, "username": "Jordan Lee", "course_of_study": "IT"}
        self.cursor.fetchall.return_value = [student]
        self.sign_in_as_student()

        response = self.client.get("/api/students/search?q=Jordan")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"students": [student]})
        query, params = self.cursor.execute.call_args.args
        self.assertIn("u.account_status = 'active'", query)
        self.assertIn("r.role_key = 'student'", query)
        self.assertIn("u.full_name LIKE %s", query)
        self.assertIn("f.status = 'pending'", query)
        self.assertEqual(params, (17, 17, 17, 17, "%Jordan%"))

    def test_student_search_without_query_suggests_active_accounts(self):
        suggestions = [
            {"user_id": 25, "username": "Jordan Lee", "course_of_study": "IT"},
            {"user_id": 26, "username": "Sam Ndlovu", "course_of_study": "Business Studies"},
        ]
        self.cursor.fetchall.return_value = suggestions
        self.sign_in_as_student()

        response = self.client.get("/api/students/search")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"students": suggestions})
        query, params = self.cursor.execute.call_args.args
        self.assertIn("u.account_status = 'active'", query)
        self.assertIn("r.role_key = 'student'", query)
        self.assertIn("f.status <> 'accepted'", query)
        self.assertEqual(params, (17, 17, 17, 17, "%%"))

    def test_sending_friend_request_creates_normalized_pending_pair(self):
        self.cursor.fetchone.side_effect = [{"user_id": 25}, None]
        self.sign_in_as_student()

        response = self.client.post("/api/friend-requests/25")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json(), {"status": "pending"})
        query, params = self.cursor.execute.call_args_list[2].args
        self.assertIn("INSERT INTO friendships", query)
        self.assertEqual(params, (17, 25, 17))
        self.connection.commit.assert_called_once()

    def test_sending_request_accepts_an_existing_incoming_invitation(self):
        self.cursor.fetchone.side_effect = [
            {"user_id": 25},
            {"requested_by": 25, "status": "pending"},
        ]
        self.sign_in_as_student()

        response = self.client.post("/api/friend-requests/25")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "accepted"})
        self.assertIn("UPDATE friendships SET status = 'accepted'", self.cursor.execute.call_args_list[2].args[0])

    def test_friend_request_response_only_updates_incoming_pending_request(self):
        self.cursor.fetchone.return_value = {"requested_by": 25, "status": "pending"}
        self.sign_in_as_student()

        response = self.client.post("/api/friend-requests/25/respond", json={"status": "accepted"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "accepted"})
        self.assertEqual(
            self.cursor.execute.call_args.args,
            ("UPDATE friendships SET status = %s WHERE user_id_a = %s AND user_id_b = %s", ("accepted", 17, 25)),
        )
        self.connection.commit.assert_called_once()

    def test_friend_request_response_rejects_outgoing_request(self):
        self.cursor.fetchone.return_value = {"requested_by": 17, "status": "pending"}
        self.sign_in_as_student()

        response = self.client.post("/api/friend-requests/25/respond", json={"status": "accepted"})

        self.assertEqual(response.status_code, 404)
        self.cursor.execute.assert_called_once()

    def test_friend_requests_endpoint_splits_incoming_and_outgoing(self):
        self.cursor.fetchall.return_value = [
            {"user_id": 25, "username": "Jordan", "direction": "incoming"},
            {"user_id": 26, "username": "Casey", "direction": "outgoing"},
        ]
        self.sign_in_as_student()

        response = self.client.get("/api/friend-requests")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "incoming": [{"user_id": 25, "username": "Jordan", "direction": "incoming"}],
            "outgoing": [{"user_id": 26, "username": "Casey", "direction": "outgoing"}],
        })

    def test_private_messages_load_only_after_friendship_acceptance(self):
        message = {
            "message_id": 9,
            "sender_id": 25,
            "recipient_id": 17,
            "encrypted_payload": json.dumps(self.encrypted_payload(25, 17)),
            "created_at": "2026-10-29 12:00:00",
        }
        self.cursor.fetchone.return_value = {"1": 1}
        self.cursor.fetchall.return_value = [message]
        self.sign_in_as_student()

        response = self.client.get("/api/friends/25/messages")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"messages": [message]})
        self.assertIn("status = 'accepted'", self.cursor.execute.call_args_list[0].args[0])
        self.assertIn("FROM private_messages", self.cursor.execute.call_args_list[1].args[0])
        self.assertIn("encrypted_payload", self.cursor.execute.call_args_list[1].args[0])
        self.assertNotIn("body", self.cursor.execute.call_args_list[1].args[0])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_private_message_send_persists_message_for_accepted_friend(self):
        payload = self.encrypted_payload()
        message = {
            "message_id": 12,
            "sender_id": 17,
            "recipient_id": 25,
            "encrypted_payload": json.dumps(payload, separators=(",", ":")),
            "created_at": "2026-10-29 12:00:00",
        }
        self.cursor.fetchone.side_effect = [{"1": 1}, message]
        self.cursor.lastrowid = 12
        self.sign_in_as_student()

        response = self.client.post(
            "/api/friends/25/messages",
            json={"encrypted_payload": payload},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json(), {"message": message})
        insert_query, insert_params = self.cursor.execute.call_args_list[1].args
        self.assertIn("INSERT INTO private_messages", insert_query)
        self.assertIn("encrypted_payload", insert_query)
        self.assertEqual(insert_params[:2], (17, 25))
        self.assertEqual(json.loads(insert_params[2]), payload)
        self.connection.commit.assert_called_once()

    def test_private_message_send_links_the_uploaded_attachment(self):
        attachment_id = "a" * 32
        message = {
            "message_id": 13,
            "sender_id": 17,
            "recipient_id": 25,
            "encrypted_payload": json.dumps(self.encrypted_payload(), separators=(",", ":")),
            "created_at": "2026-10-29 12:00:00",
        }
        self.cursor.fetchone.side_effect = [
            {"1": 1},
            {"attachment_id": attachment_id},
            message,
        ]
        self.cursor.lastrowid = 13
        self.cursor.rowcount = 1
        self.sign_in_as_student()

        response = self.client.post(
            "/api/friends/25/messages",
            json={
                "encrypted_payload": self.encrypted_payload(),
                "attachment_id": attachment_id,
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json(), {"message": message})
        update_query, update_params = self.cursor.execute.call_args_list[3].args
        self.assertIn("UPDATE private_message_attachments SET message_id", update_query)
        self.assertEqual(update_params, (13, attachment_id, 17, 25))
        self.connection.commit.assert_called_once()

    def test_private_attachment_upload_stores_only_randomized_blob_name(self):
        with TemporaryDirectory() as upload_directory:
            with patch.object(backend, "PRIVATE_MESSAGE_UPLOAD_DIR", Path(upload_directory)):
                self.cursor.fetchone.return_value = {"1": 1}
                self.sign_in_as_student()
                encrypted_bytes = b"encrypted-file-bytes"

                response = self.client.post(
                    "/api/friends/25/attachments",
                    data=encrypted_bytes,
                    content_type="application/octet-stream",
                )

                self.assertEqual(response.status_code, 201)
                self.assertRegex(response.get_json()["attachment_id"], r"^[a-f0-9]{32}$")
                query, params = self.cursor.execute.call_args_list[1].args
                self.assertIn("INSERT INTO private_message_attachments", query)
                self.assertRegex(params[3], r"^[a-f0-9]{32}$")
                self.assertEqual(params[4], len(encrypted_bytes))
                self.assertEqual((Path(upload_directory) / params[3]).read_bytes(), encrypted_bytes)
                self.connection.commit.assert_called_once()

    def test_private_attachment_upload_requires_accepted_friendship(self):
        with TemporaryDirectory() as upload_directory:
            with patch.object(backend, "PRIVATE_MESSAGE_UPLOAD_DIR", Path(upload_directory)):
                self.cursor.fetchone.return_value = None
                self.sign_in_as_student()

                response = self.client.post(
                    "/api/friends/25/attachments",
                    data=b"x" * 16,
                    content_type="application/octet-stream",
                )

                self.assertEqual(response.status_code, 403)
                self.assertEqual(list(Path(upload_directory).iterdir()), [])
                self.assertEqual(self.cursor.execute.call_count, 1)

    def test_private_attachment_upload_enforces_encrypted_size_limit(self):
        self.sign_in_as_student()

        response = self.client.post(
            "/api/friends/25/attachments",
            data=b"x" * (backend.MAX_ENCRYPTED_PRIVATE_ATTACHMENT_BYTES + 1),
            content_type="application/octet-stream",
        )

        self.assertEqual(response.status_code, 413)
        self.connection.cursor.assert_not_called()

    def test_private_attachment_download_requires_a_linked_message(self):
        self.cursor.fetchone.side_effect = [{"1": 1}, None]
        self.sign_in_as_student()

        response = self.client.get(f"/api/friends/25/attachments/{'a' * 32}")

        self.assertEqual(response.status_code, 404)
        query = self.cursor.execute.call_args_list[1].args[0]
        self.assertIn("JOIN private_messages", query)
        self.assertIn("a.message_id IS NOT NULL", query)

    def test_private_attachment_download_is_friendship_authorized(self):
        attachment_id = "a" * 32
        storage_name = "b" * 32
        with TemporaryDirectory() as upload_directory:
            with patch.object(backend, "PRIVATE_MESSAGE_UPLOAD_DIR", Path(upload_directory)):
                (Path(upload_directory) / storage_name).write_bytes(b"opaque-ciphertext")
                self.cursor.fetchone.side_effect = [
                    {"1": 1},
                    {"storage_name": storage_name},
                ]
                self.sign_in_as_student()

                response = self.client.get(
                    f"/api/friends/25/attachments/{attachment_id}"
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, b"opaque-ciphertext")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                response.close()

    def test_private_messages_are_forbidden_before_friendship_acceptance(self):
        self.cursor.fetchone.return_value = None
        self.sign_in_as_student()

        response = self.client.post(
            "/api/friends/25/messages",
            json={"encrypted_payload": self.encrypted_payload()},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.cursor.execute.call_count, 1)

    def test_private_message_rejects_invalid_or_wrong_conversation_payload(self):
        self.sign_in_as_student()

        missing_payload = self.client.post("/api/friends/25/messages", json={"body": "plaintext"})
        wrong_conversation = self.encrypted_payload(sender_id=17, recipient_id=26)
        mismatch_response = self.client.post(
            "/api/friends/25/messages",
            json={"encrypted_payload": wrong_conversation},
        )
        malformed_response = self.client.post(
            "/api/friends/25/messages",
            json={"encrypted_payload": {"v": 1, "ciphertext": "not-base64"}},
        )

        self.assertEqual(missing_payload.status_code, 400)
        self.assertEqual(mismatch_response.status_code, 400)
        self.assertEqual(malformed_response.status_code, 400)
        self.cursor.execute.assert_not_called()

    def test_student_can_register_an_encryption_key_once(self):
        public_key = self.public_key_bundle()
        self.cursor.fetchone.return_value = {"public_key": public_key}
        self.sign_in_as_student()

        response = self.client.put("/api/encryption-key", json={"public_key": public_key})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"public_key": public_key})
        self.assertIn("INSERT IGNORE INTO user_encryption_keys", self.cursor.execute.call_args_list[0].args[0])
        self.connection.commit.assert_called_once()

    def test_student_cannot_replace_an_encryption_key(self):
        existing_key = self.public_key_bundle()
        replacement_key = json.dumps({
            "v": 1,
            "encryption": base64.b64encode(b"n" * 294).decode("ascii"),
            "signing": base64.b64encode(b"t" * 91).decode("ascii"),
        })
        self.cursor.fetchone.return_value = {"public_key": existing_key}
        self.sign_in_as_student()

        response = self.client.put(
            "/api/encryption-key",
            json={"public_key": replacement_key},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.cursor.execute.call_count, 2)

    def test_encryption_key_registration_rejects_invalid_bundle(self):
        self.sign_in_as_student()

        response = self.client.put("/api/encryption-key", json={"public_key": "not a key"})

        self.assertEqual(response.status_code, 400)
        self.cursor.execute.assert_not_called()

    def test_friend_encryption_key_requires_accepted_friendship(self):
        self.cursor.fetchone.side_effect = [{"1": 1}, {"public_key": self.public_key_bundle()}]
        self.sign_in_as_student()

        response = self.client.get("/api/friends/25/encryption-key")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"public_key": self.public_key_bundle()})
        self.assertIn("status = 'accepted'", self.cursor.execute.call_args_list[0].args[0])

    def test_friend_encryption_key_is_not_disclosed_to_non_friends(self):
        self.cursor.fetchone.return_value = None
        self.sign_in_as_student()

        response = self.client.get("/api/friends/25/encryption-key")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.cursor.execute.call_count, 1)

    def test_friends_endpoint_returns_only_accepted_active_student_accounts(self):
        friends = [{"user_id": 25, "username": "Jordan Lee", "course_of_study": "IT"}]
        self.cursor.fetchall.return_value = friends
        self.sign_in_as_student()

        response = self.client.get("/api/friends")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"friends": friends})
        query, params = self.cursor.execute.call_args.args
        self.assertIn("f.status = 'accepted'", query)
        self.assertIn("u.account_status = 'active'", query)
        self.assertIn("r.role_key = 'student'", query)
        self.assertEqual(params, (17, 17, 17))

    def test_friends_endpoint_requires_student_sign_in(self):
        response = self.client.get("/api/friends")

        self.assertEqual(response.status_code, 401)
        self.connection.cursor.assert_not_called()

    def test_student_search_requires_student_sign_in(self):
        response = self.client.get("/api/students/search?q=Jordan")

        self.assertEqual(response.status_code, 401)
        self.connection.cursor.assert_not_called()

    def test_student_search_rejects_long_query(self):
        self.sign_in_as_student()

        response = self.client.get(f"/api/students/search?q={'x' * 101}")

        self.assertEqual(response.status_code, 400)
        self.connection.cursor.assert_not_called()

    def test_resource_upload_saves_file_as_pending_for_admin_review(self):
        self.cursor.lastrowid = 21
        self.sign_in_as_student()

        with TemporaryDirectory() as upload_directory:
            with patch.object(backend, "RESOURCE_UPLOAD_DIR", Path(upload_directory)):
                response = self.client.post(
                    "/api/resources",
                    data={
                        "title": "Business Administration memo",
                        "description": "Exam practice",
                        "resource_category": "Business Administration",
                        "resource_type": "past_paper",
                        "file": (BytesIO(b"%PDF-1.7\nexample"), "memo.pdf", "application/pdf"),
                    },
                    content_type="multipart/form-data",
                )

                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.get_json()["status"], "pending")
                query, params = self.cursor.execute.call_args.args
                self.assertIn("INSERT INTO resources", query)
                self.assertIn("resource_category", query)
                self.assertEqual(params[1:4], ("Business Administration memo", "Exam practice", "past_paper"))
                self.assertEqual(params[4], "Business Administration")
                self.assertTrue((Path(upload_directory) / params[5]).is_file())
                self.connection.commit.assert_called_once()

    def test_resource_upload_rejects_mismatched_file_content(self):
        self.sign_in_as_student()

        response = self.client.post(
            "/api/resources",
            data={
                "title": "Not a PDF",
                "resource_category": "IT",
                "resource_type": "notes",
                "file": (BytesIO(b"not a pdf"), "notes.pdf", "application/pdf"),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.cursor.execute.assert_not_called()

    def test_resource_upload_requires_student_sign_in(self):
        response = self.client.post(
            "/api/resources",
            data={"title": "Notes", "resource_category": "IT", "resource_type": "notes"},
        )

        self.assertEqual(response.status_code, 401)
        self.connection.cursor.assert_not_called()

    def test_admin_can_approve_pending_resource(self):
        self.cursor.fetchone.side_effect = [
            {"full_name": "Test Admin"},
            {"status": "pending"},
        ]
        with self.client.session_transaction() as session:
            session["user_id"] = 4
            session["role"] = "admin"

        response = self.client.post("/api/admin/resources/21/review", json={"status": "approved"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"resource_id": 21, "status": "approved"})
        update_query, update_params = self.cursor.execute.call_args_list[2].args
        self.assertIn("UPDATE resources SET status", update_query)
        self.assertEqual(update_params, ("approved", 4, 21))
        self.connection.commit.assert_called_once()

    def test_non_admin_cannot_review_resources(self):
        self.sign_in_as_student()

        response = self.client.post("/api/admin/resources/21/review", json={"status": "approved"})

        self.assertEqual(response.status_code, 403)
        self.connection.cursor.assert_not_called()

    def test_communities_endpoint_counts_active_members(self):
        self.cursor.fetchall.return_value = [
            {"community_id": 3, "name": "Programming", "member_count": 2, "is_member": 1}
        ]
        self.sign_in_as_student()

        response = self.client.get("/api/communities")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["communities"][0]["member_count"], 2)
        query = self.cursor.execute.call_args.args[0]
        self.assertIn("members.status = 'active'", query)
        self.assertIn("c.visibility = 'public'", query)

    def test_community_messages_require_active_membership(self):
        self.cursor.fetchone.return_value = None
        self.sign_in_as_student()

        response = self.client.get("/api/communities/3/messages")

        self.assertEqual(response.status_code, 403)
        self.assertIn("Join this community", response.get_json()["message"])
        self.cursor.execute.assert_called_once()

    def test_community_messages_include_pins_and_recent_messages(self):
        self.cursor.fetchone.return_value = {"member_role": "member"}
        self.cursor.fetchall.return_value = [{
            "message_id": 41,
            "community_id": 3,
            "author_id": 17,
            "author_name": "Jordan Lee",
            "content": "Important update",
            "message_type": "announcement",
            "is_highlighted": 1,
            "is_pinned": 1,
            "pinned_by": 17,
            "pinned_at": datetime(2026, 11, 3, 10, 0),
            "created_at": datetime(2026, 11, 3, 9, 0),
        }]
        self.sign_in_as_student()

        response = self.client.get("/api/communities/3/messages")

        self.assertEqual(response.status_code, 200)
        message = response.get_json()["messages"][0]
        self.assertEqual(message["message_type"], "announcement")
        self.assertEqual(message["pinned_at"], "2026-11-03 10:00:00")
        self.assertTrue(message["can_manage"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        query = self.cursor.execute.call_args_list[1].args[0]
        self.assertIn("m.is_pinned = TRUE", query)
        self.assertIn("LIMIT 100", query)

    def test_community_member_can_send_an_announcement(self):
        self.cursor.fetchone.side_effect = [
            {"member_role": "member"},
            {
                "message_id": 41,
                "community_id": 3,
                "author_id": 17,
                "author_name": "Jordan Lee",
                "content": "Class is moved",
                "message_type": "announcement",
                "is_highlighted": 0,
                "is_pinned": 0,
                "pinned_by": None,
                "pinned_at": None,
                "created_at": datetime(2026, 11, 3, 9, 0),
            },
        ]
        self.cursor.lastrowid = 41
        self.sign_in_as_student()

        response = self.client.post(
            "/api/communities/3/messages",
            json={"content": " Class is moved ", "message_type": "announcement"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["message"]["content"], "Class is moved")
        self.assertEqual(response.get_json()["message"]["message_type"], "announcement")
        self.assertEqual(
            self.cursor.execute.call_args_list[1].args[1],
            (3, 17, "Class is moved", "announcement"),
        )
        self.connection.commit.assert_called_once()

    def test_community_author_can_pin_and_highlight_own_message(self):
        self.cursor.fetchone.side_effect = [
            {"member_role": "member"},
            {"author_id": 17},
            {
                "message_id": 41,
                "community_id": 3,
                "author_id": 17,
                "author_name": "Jordan Lee",
                "content": "Important update",
                "message_type": "message",
                "is_highlighted": 1,
                "is_pinned": 1,
                "pinned_by": 17,
                "pinned_at": datetime(2026, 11, 3, 10, 0),
                "created_at": datetime(2026, 11, 3, 9, 0),
            },
        ]
        self.sign_in_as_student()

        response = self.client.patch(
            "/api/communities/3/messages/41",
            json={"is_pinned": True, "is_highlighted": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["message"]["is_pinned"])
        self.assertTrue(response.get_json()["message"]["is_highlighted"])
        update_query, update_params = self.cursor.execute.call_args_list[2].args
        self.assertIn("is_highlighted = %s", update_query)
        self.assertIn("is_pinned = TRUE", update_query)
        self.assertIn("pinned_at = CURRENT_TIMESTAMP", update_query)
        self.assertEqual(update_params, (True, 17, 41))
        self.connection.commit.assert_called_once()

    def test_community_member_cannot_pin_another_members_message(self):
        self.cursor.fetchone.side_effect = [
            {"member_role": "member"},
            {"author_id": 25},
        ]
        self.sign_in_as_student()

        response = self.client.patch(
            "/api/communities/3/messages/41",
            json={"is_pinned": True},
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("own messages", response.get_json()["message"])
        self.connection.commit.assert_not_called()

    def test_community_author_can_unpin_without_changing_highlight(self):
        self.cursor.fetchone.side_effect = [
            {"member_role": "member"},
            {"author_id": 17},
            {
                "message_id": 41,
                "community_id": 3,
                "author_id": 17,
                "author_name": "Jordan Lee",
                "content": "Important update",
                "message_type": "message",
                "is_highlighted": 1,
                "is_pinned": 0,
                "pinned_by": None,
                "pinned_at": None,
                "created_at": datetime(2026, 11, 3, 9, 0),
            },
        ]
        self.sign_in_as_student()

        response = self.client.patch(
            "/api/communities/3/messages/41",
            json={"is_pinned": False},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["message"]["is_highlighted"])
        update_query, update_params = self.cursor.execute.call_args_list[2].args
        self.assertIn("is_pinned = FALSE", update_query)
        self.assertIn("pinned_by = NULL", update_query)
        self.assertIn("pinned_at = NULL", update_query)
        self.assertEqual(update_params, (41,))
        self.connection.commit.assert_called_once()

    def test_joining_community_inserts_membership_and_returns_current_count(self):
        self.cursor.fetchone.side_effect = [
            {"visibility": "public", "status": "active"},
            None,
            {"member_count": 3},
        ]
        self.sign_in_as_student()

        response = self.client.post("/api/communities/3/join")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"member_count": 3, "is_member": True})
        self.assertIn(
            "INSERT INTO community_members",
            self.cursor.execute.call_args_list[2].args[0],
        )
        self.connection.commit.assert_called_once()

    def test_admin_course_materials_returns_it_and_business_administration_folders(self):
        self.sign_in_as_admin()
        self.cursor.fetchone.return_value = {"full_name": "Test Admin"}
        self.cursor.fetchall.return_value = [
            {
                "resource_id": 51,
                "title": "IT Notes",
                "description": None,
                "resource_type": "notes",
                "resource_category": "IT",
                "file_url": None,
                "source_url": "https://example.com/it-notes",
                "created_at": datetime(2026, 10, 31),
                "uploader_name": "Test Admin",
            },
            {
                "resource_id": 52,
                "title": "BA Article",
                "description": None,
                "resource_type": "article",
                "resource_category": "Business Administration",
                "file_url": None,
                "source_url": None,
                "created_at": datetime(2026, 10, 30),
                "uploader_name": "Test Admin",
            },
        ]

        response = self.client.get("/api/admin/course-materials")

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["course_count"], 2)
        self.assertEqual(
            [folder["key"] for folder in payload["categories"]],
            ["IT", "Business Administration"],
        )
        self.assertEqual([folder["material_count"] for folder in payload["categories"]], [1, 1])
        self.assertEqual(
            payload["categories"][0]["materials"][0]["material_url"],
            "https://example.com/it-notes",
        )
        self.assertIn("r.status = 'approved'", self.cursor.execute.call_args.args[0])

    def test_admin_can_publish_course_material_directly_to_student_library(self):
        self.sign_in_as_admin()
        self.cursor.fetchone.return_value = {"full_name": "Test Admin"}
        self.cursor.lastrowid = 84

        with TemporaryDirectory() as upload_directory:
            with (
                patch.object(backend, "RESOURCE_UPLOAD_DIR", Path(upload_directory)),
                patch.object(backend, "valid_resource_file", return_value=True),
            ):
                response = self.client.post(
                    "/api/admin/course-materials",
                    data={
                        "title": "IT Revision Notes",
                        "description": "Exam revision",
                        "resource_category": "IT",
                        "resource_type": "notes",
                        "file": (BytesIO(b"fake pdf"), "revision.pdf", "application/pdf"),
                    },
                    content_type="multipart/form-data",
                )

                self.assertEqual(response.status_code, 201, response.get_json())
                self.assertEqual(response.get_json()["status"], "approved")
                insert_call = next(
                    call for call in self.cursor.execute.call_args_list
                    if "INSERT INTO resources" in call.args[0]
                )
                self.assertIn("'approved'", insert_call.args[0])
                self.assertEqual(
                    insert_call.args[1][2:6],
                    ("IT Revision Notes", "Exam revision", "notes", "IT"),
                )
                self.assertTrue((Path(upload_directory) / insert_call.args[1][-1]).is_file())
                audit_call = next(
                    call for call in self.cursor.execute.call_args_list
                    if "INSERT INTO admin_audit_log" in call.args[0]
                )
                self.assertEqual(audit_call.args[1][:4], (1, "course_material.added", "resource", 84))
                self.connection.commit.assert_called_once()

    def test_admin_can_archive_course_material(self):
        self.sign_in_as_admin()
        self.cursor.fetchone.side_effect = [
            {"full_name": "Test Admin"},
            {
                "title": "IT Notes",
                "resource_category": "IT",
                "status": "approved",
            },
        ]

        response = self.client.post("/api/admin/course-materials/51/archive")

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["status"], "archived")
        update_call = next(
            call for call in self.cursor.execute.call_args_list
            if "UPDATE resources SET status = 'archived'" in call.args[0]
        )
        self.assertEqual(update_call.args[1], (51,))
        self.connection.commit.assert_called_once()

    def test_creating_community_adds_creator_as_owner(self):
        self.cursor.lastrowid = 12
        self.sign_in_as_student()

        response = self.client.post(
            "/api/communities",
            json={
                "name": "Database Study Group",
                "category": "Database",
                "description": "Weekly SQL practice",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.get_json()["community"],
            {
                "community_id": 12,
                "name": "Database Study Group",
                "description": "Weekly SQL practice",
                "community_group": "IT Communities",
                "community_category": "Database",
                "course_name": "Database",
                "member_count": 1,
                "is_member": True,
            },
        )
        self.assertIn("INSERT INTO communities", self.cursor.execute.call_args_list[0].args[0])
        self.assertIn("community_group", self.cursor.execute.call_args_list[0].args[0])
        self.assertEqual(
            self.cursor.execute.call_args_list[0].args[1],
            (17, "Database Study Group", "Weekly SQL practice", "IT Communities", "Database"),
        )
        self.assertIn("INSERT INTO community_members", self.cursor.execute.call_args_list[1].args[0])
        self.connection.commit.assert_called_once()

    def test_creating_ba_community_uses_ba_topics_and_adds_creator_as_owner(self):
        self.cursor.lastrowid = 13
        self.sign_in_as_student()

        response = self.client.post(
            "/api/communities",
            json={
                "name": "Accounting Circle",
                "group": "BA Communities",
                "category": "Accounting",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["community"]["community_group"], "BA Communities")
        self.assertEqual(response.get_json()["community"]["community_category"], "Accounting")
        self.assertEqual(
            self.cursor.execute.call_args_list[0].args[1],
            (17, "Accounting Circle", None, "BA Communities", "Accounting"),
        )
        self.assertIn("INSERT INTO community_members", self.cursor.execute.call_args_list[1].args[0])
        self.connection.commit.assert_called_once()

    def test_creating_community_rejects_topic_from_another_group(self):
        self.sign_in_as_student()

        response = self.client.post(
            "/api/communities",
            json={
                "name": "Accounting Circle",
                "group": "IT Communities",
                "category": "Accounting",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.cursor.execute.assert_not_called()

    def test_communities_endpoint_includes_community_group(self):
        self.cursor.fetchall.return_value = [
            {
                "community_id": 3,
                "name": "Accounting",
                "community_group": "BA Communities",
                "community_category": "Accounting",
                "course_name": "Accounting",
                "member_count": 1,
                "is_member": 0,
            }
        ]
        self.sign_in_as_student()

        response = self.client.get("/api/communities")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["communities"][0]["community_group"],
            "BA Communities",
        )
        self.assertIn("c.community_group", self.cursor.execute.call_args.args[0])

    def test_creating_community_rejects_unknown_topics(self):
        self.sign_in_as_student()

        response = self.client.post(
            "/api/communities",
            json={"name": "Study group", "category": "Other"},
        )

        self.assertEqual(response.status_code, 400)
        self.cursor.execute.assert_not_called()

    def test_creating_community_requires_student_sign_in(self):
        response = self.client.post(
            "/api/communities",
            json={"name": "Study group", "category": "Database"},
        )

        self.assertEqual(response.status_code, 401)
        self.connection.cursor.assert_not_called()

    def test_dashboard_data_endpoints_require_student_sign_in(self):
        self.assertEqual(self.client.get("/api/resources").status_code, 401)
        self.assertEqual(self.client.get("/api/communities").status_code, 401)
        self.connection.cursor.assert_not_called()


if __name__ == "__main__":
    unittest.main()

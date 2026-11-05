import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, send_from_directory, session
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
RESOURCE_UPLOAD_DIR = BASE_DIR / "uploads" / "resources"
PRIVATE_MESSAGE_UPLOAD_DIR = BASE_DIR / "uploads" / "private_messages"
load_dotenv(BASE_DIR / ".env")

RESOURCE_CATEGORIES = ("IT", "Business Administration")
RESOURCE_TYPES = ("notes", "article", "past_paper")
MAX_RESOURCE_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PRIVATE_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ENCRYPTED_PRIVATE_ATTACHMENT_BYTES = MAX_PRIVATE_ATTACHMENT_BYTES + 16
RESOURCE_FILE_EXTENSIONS = {".pdf", ".doc", ".docx"}
STUDENT_SESSION_GRACE_SECONDS = 120
COMMUNITY_CATEGORIES = (
    "Database",
    "Information Systems",
    "Software Engineering",
    "Programming C++",
    "Programming JAVA",
    "Programming Python",
    "Data Science",
    "Robotics",
    "CyberSecurity",
    "Machine Learning",
    "Mathematics",
    "Cloud Computing",
)
BUSINESS_COMMUNITY_CATEGORIES = (
    "Accounting",
    "Commercial law",
    "Business Management",
    "Supply Chain",
    "Economics",
    "Information Systems",
    "Business Ethics",
    "Industrial Phsycology",
    "Statistics",
)
COMMUNITY_GROUP_CATEGORIES = {
    "IT Communities": COMMUNITY_CATEGORIES,
    "BA Communities": BUSINESS_COMMUNITY_CATEGORIES,
}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", ""),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,
)


@contextmanager
def database_connection():
    connection = mysql.connector.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "python_app"),
        connection_timeout=5,
    )
    try:
        yield connection
    finally:
        connection.close()


def json_error(message, status):
    return jsonify({"message": message}), status


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_error):
    return json_error("The uploaded file is larger than the 10 MB limit.", 413)


def active_admin(cursor, user_id):
    cursor.execute(
        "SELECT u.full_name FROM users AS u "
        "JOIN user_roles AS ur ON ur.user_id = u.user_id "
        "JOIN roles AS r ON r.role_id = ur.role_id "
        "WHERE u.user_id = %s AND u.account_status = 'active' "
        "AND r.role_key = 'admin' LIMIT 1",
        (user_id,),
    )
    return cursor.fetchone()


def record_admin_audit(cursor, admin_user_id, action, target_type, target_id, details=None):
    cursor.execute(
        "INSERT INTO admin_audit_log "
        "(admin_user_id, action, target_type, target_id, details) "
        "VALUES (%s, %s, %s, %s, %s)",
        (admin_user_id, action, target_type, target_id, details),
    )


def close_student_activity(cursor, activity_id, user_id):
    if activity_id:
        cursor.execute(
            "UPDATE student_login_sessions "
            "SET ended_at = LEAST(CURRENT_TIMESTAMP, "
            "DATE_ADD(last_seen_at, INTERVAL %s SECOND)) "
            "WHERE activity_id = %s AND user_id = %s AND ended_at IS NULL",
            (STUDENT_SESSION_GRACE_SECONDS, activity_id, user_id),
        )


def add_daily_activity_seconds(daily_seconds, start, end):
    while start < end:
        following_day = start.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        segment_end = min(end, following_day)
        daily_seconds[start.day - 1] += (segment_end - start).total_seconds()
        start = segment_end


def valid_resource_file(upload):
    extension = Path(upload.filename or "").suffix.lower()
    if extension not in RESOURCE_FILE_EXTENSIONS:
        return False

    signature = upload.stream.read(8)
    upload.stream.seek(0)
    if extension == ".pdf":
        return signature.startswith(b"%PDF-")
    if extension == ".doc":
        return signature.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
    if extension == ".docx" and signature.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(upload.stream) as archive:
                valid_docx = "word/document.xml" in archive.namelist()
        except zipfile.BadZipFile:
            return False
        finally:
            upload.stream.seek(0)
        return valid_docx
    return False


def resource_download_name(title, file_name):
    extension = Path(file_name).suffix.lower()
    return f"{secure_filename(title) or 'resource'}{extension}"


def is_stored_resource_file(file_name):
    return bool(re.fullmatch(r"[a-f0-9]{32}\.(pdf|doc|docx)", file_name or ""))


def hash_otp(otp):
    key = app.config["SECRET_KEY"].encode("utf-8")
    return hmac.new(key, otp.encode("ascii"), hashlib.sha256).hexdigest()


def send_otp_email(recipient, otp):
    host = os.environ.get("SMTP_HOST", "").strip()
    sender = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "")).strip()
    if not host:
        raise RuntimeError("Set SMTP_HOST in .env to enable password reset email.")
    if not sender:
        raise RuntimeError("Set SMTP_FROM or SMTP_USER in .env to enable password reset email.")

    message = EmailMessage()
    message["Subject"] = "Your Acadex password reset code"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        f"Your Acadex password reset code is {otp}. It expires in 10 minutes.\n\n"
        "If you did not request this code, you can ignore this email."
    )

    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    use_ssl = os.environ.get("SMTP_USE_SSL", "false").lower() == "true"

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


@app.get("/")
def homepage():
    return send_from_directory(BASE_DIR, "AcadexHomepage.html")


@app.get("/indext.html")
def login_page():
    return send_from_directory(BASE_DIR, "indext.html")


@app.get("/dashboard.html")
def student_dashboard():
    if "user_id" not in session:
        return redirect("/indext.html?tab=login")
    if session.get("role") != "student":
        return redirect("/AdminPage.html")
    return send_from_directory(BASE_DIR, "dashboard.html")


@app.get("/api/resources")
def approved_resources():
    if "user_id" not in session:
        return json_error("Sign in to view approved resources.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can view the library.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT r.resource_id, r.title, r.description, r.resource_type, "
                    "r.resource_category, r.file_url, r.source_url, r.created_at, "
                    "c.name AS course_name, "
                    "u.full_name AS uploader_name "
                    "FROM resources AS r "
                    "LEFT JOIN courses AS c ON c.course_id = r.course_id "
                    "JOIN users AS u ON u.user_id = r.uploaded_by "
                    "WHERE r.status = 'approved' "
                    "ORDER BY r.created_at DESC, r.resource_id DESC"
                )
                resources = cursor.fetchall()
                for resource in resources:
                    if is_stored_resource_file(resource.get("file_url")):
                        resource["file_url"] = f"/api/resources/{resource['resource_id']}/file"
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading approved resources")
        return json_error("Could not load approved resources from python_app.", 503)

    return jsonify({"resources": resources})


@app.get("/api/resource-stats")
def resource_stats():
    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT COUNT(*) AS resource_count, "
                    "COALESCE(SUM(resource_type = 'notes'), 0) AS notes_count, "
                    "COALESCE(SUM(resource_type = 'past_paper'), 0) AS past_paper_count, "
                    "COALESCE(SUM(resource_category = 'IT'), 0) AS it_material_count, "
                    "COALESCE(SUM(resource_category IN ('Business Administration', 'Business Studies')), 0) "
                    "AS ba_material_count "
                    "FROM resources WHERE status = 'approved'"
                )
                stats = cursor.fetchone()
                stats["course_count"] = len(RESOURCE_CATEGORIES)
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading public resource statistics")
        return json_error("Could not load resource statistics from python_app.", 503)

    response = jsonify(stats)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/resources")
def upload_resource():
    if "user_id" not in session:
        return json_error("Sign in to upload a resource.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can upload resources.", 403)

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("resource_category", "")
    resource_type = request.form.get("resource_type", "")
    upload = request.files.get("file")
    if not title or len(title) > 220:
        return json_error("Enter a resource title up to 220 characters.", 400)
    if len(description) > 2000:
        return json_error("The description must be 2000 characters or fewer.", 400)
    if category not in RESOURCE_CATEGORIES:
        return json_error("Choose IT or Business Administration.", 400)
    if resource_type not in RESOURCE_TYPES:
        return json_error("Choose Notes, Articles, or Past Papers & Memos.", 400)
    if not upload or not upload.filename:
        return json_error("Choose a PDF, DOC, or DOCX file to upload.", 400)
    if not valid_resource_file(upload):
        return json_error("Upload a valid PDF, DOC, or DOCX document.", 400)

    extension = Path(upload.filename).suffix.lower()
    temporary_name = f"{secrets.token_hex(16)}{extension}"
    temporary_path = RESOURCE_UPLOAD_DIR / temporary_name
    try:
        RESOURCE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        upload.save(temporary_path)
        if temporary_path.stat().st_size > MAX_RESOURCE_UPLOAD_BYTES:
            temporary_path.unlink()
            return json_error("The uploaded file is larger than the 10 MB limit.", 413)

        with database_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "INSERT INTO resources "
                    "(course_id, uploaded_by, title, description, resource_type, "
                    "resource_category, file_url, status) "
                    "VALUES (NULL, %s, %s, %s, %s, %s, %s, 'pending')",
                    (
                        session["user_id"],
                        title,
                        description or None,
                        resource_type,
                        category,
                        temporary_name,
                    ),
                )
                resource_id = cursor.lastrowid
                connection.commit()
            finally:
                cursor.close()
    except OSError:
        app.logger.exception("File system error while saving an uploaded resource")
        temporary_path.unlink(missing_ok=True)
        return json_error("Could not save the uploaded resource.", 500)
    except mysql.connector.Error:
        app.logger.exception("MySQL error while recording an uploaded resource")
        temporary_path.unlink(missing_ok=True)
        return json_error("Could not submit the resource for review.", 503)

    return jsonify(
        {
            "resource_id": resource_id,
            "status": "pending",
            "message": "Resource submitted. It will appear in the library after admin approval.",
        }
    ), 201


@app.get("/api/resources/<int:resource_id>/file")
def approved_resource_file(resource_id):
    if "user_id" not in session:
        return json_error("Sign in to download resources.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can download library resources.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT title, file_url FROM resources "
                    "WHERE resource_id = %s AND status = 'approved' LIMIT 1",
                    (resource_id,),
                )
                resource = cursor.fetchone()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading an approved resource file")
        return json_error("Could not load the resource from python_app.", 503)

    if not resource or not is_stored_resource_file(resource["file_url"]):
        return json_error("This approved resource file is unavailable.", 404)
    file_name = Path(resource["file_url"]).name
    response = send_from_directory(
        RESOURCE_UPLOAD_DIR,
        file_name,
        as_attachment=True,
        download_name=resource_download_name(resource["title"], file_name),
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/api/students/search")
def search_active_students():
    if "user_id" not in session:
        return json_error("Sign in to search students.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can search students.", 403)

    term = request.args.get("q", "").strip()
    if len(term) > 100:
        return json_error("Search terms must be 100 characters or fewer.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT u.user_id, u.full_name AS username, "
                    "p.course_of_study, f.status AS friendship_status, "
                    "CASE WHEN f.status = 'pending' AND f.requested_by = %s "
                    "THEN 'outgoing' WHEN f.status = 'pending' THEN 'incoming' "
                    "ELSE NULL END AS request_direction "
                    "FROM users AS u "
                    "JOIN user_roles AS ur ON ur.user_id = u.user_id "
                    "JOIN roles AS r ON r.role_id = ur.role_id "
                    "LEFT JOIN profiles AS p ON p.user_id = u.user_id "
                    "LEFT JOIN friendships AS f ON f.user_id_a = LEAST(%s, u.user_id) "
                    "AND f.user_id_b = GREATEST(%s, u.user_id) "
                    "WHERE u.account_status = 'active' AND r.role_key = 'student' "
                    "AND u.user_id <> %s AND u.full_name LIKE %s "
                    "AND (f.status IS NULL OR f.status <> 'accepted') "
                    "AND (f.status IS NULL OR f.status <> 'blocked') "
                    "ORDER BY u.full_name, u.user_id LIMIT 30",
                    (
                        session["user_id"],
                        session["user_id"],
                        session["user_id"],
                        session["user_id"],
                        f"%{term}%",
                    ),
                )
                students = cursor.fetchall()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while searching active student accounts")
        return json_error("Could not search student accounts in python_app.", 503)

    return jsonify({"students": students})


@app.get("/api/friend-requests")
def friend_requests():
    if "user_id" not in session:
        return json_error("Sign in to view friend requests.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can view friend requests.", 403)

    user_id = session["user_id"]
    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT CASE WHEN f.user_id_a = %s THEN f.user_id_b "
                    "ELSE f.user_id_a END AS user_id, u.full_name AS username, "
                    "CASE WHEN f.requested_by = %s THEN 'outgoing' ELSE 'incoming' END "
                    "AS direction "
                    "FROM friendships AS f "
                    "JOIN users AS u ON u.user_id = CASE "
                    "WHEN f.user_id_a = %s THEN f.user_id_b ELSE f.user_id_a END "
                    "WHERE (f.user_id_a = %s OR f.user_id_b = %s) "
                    "AND f.status = 'pending' AND u.account_status = 'active' "
                    "ORDER BY f.updated_at DESC",
                    (user_id, user_id, user_id, user_id, user_id),
                )
                requests = cursor.fetchall()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading friend requests")
        return json_error("Could not load friend requests from python_app.", 503)

    return jsonify({
        "incoming": [item for item in requests if item["direction"] == "incoming"],
        "outgoing": [item for item in requests if item["direction"] == "outgoing"],
    })


@app.post("/api/friend-requests/<int:student_id>")
def send_friend_request(student_id):
    if "user_id" not in session:
        return json_error("Sign in to invite students.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can invite students.", 403)
    user_id = session["user_id"]
    if student_id == user_id:
        return json_error("You cannot invite your own account.", 400)

    user_a, user_b = sorted((user_id, student_id))
    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT u.user_id FROM users AS u "
                    "JOIN user_roles AS ur ON ur.user_id = u.user_id "
                    "JOIN roles AS r ON r.role_id = ur.role_id "
                    "WHERE u.user_id = %s AND u.account_status = 'active' "
                    "AND r.role_key = 'student' LIMIT 1",
                    (student_id,),
                )
                if not cursor.fetchone():
                    return json_error("That active student account was not found.", 404)

                cursor.execute(
                    "SELECT requested_by, status FROM friendships "
                    "WHERE user_id_a = %s AND user_id_b = %s FOR UPDATE",
                    (user_a, user_b),
                )
                relationship = cursor.fetchone()
                if relationship and relationship["status"] == "blocked":
                    return json_error("This invitation cannot be sent.", 403)
                if relationship and relationship["status"] == "accepted":
                    return json_error("You are already friends.", 409)
                if relationship and relationship["status"] == "pending":
                    if relationship["requested_by"] == student_id:
                        cursor.execute(
                            "UPDATE friendships SET status = 'accepted' "
                            "WHERE user_id_a = %s AND user_id_b = %s",
                            (user_a, user_b),
                        )
                        connection.commit()
                        return jsonify({"status": "accepted"})
                    return json_error("Your invitation is already pending.", 409)
                if relationship:
                    cursor.execute(
                        "UPDATE friendships SET requested_by = %s, status = 'pending' "
                        "WHERE user_id_a = %s AND user_id_b = %s",
                        (user_id, user_a, user_b),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO friendships "
                        "(user_id_a, user_id_b, requested_by, status) "
                        "VALUES (%s, %s, %s, 'pending')",
                        (user_a, user_b, user_id),
                    )
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while sending a friend request")
        return json_error("Could not send this invitation to python_app.", 503)

    return jsonify({"status": "pending"}), 201


@app.post("/api/friend-requests/<int:student_id>/respond")
def respond_to_friend_request(student_id):
    if "user_id" not in session:
        return json_error("Sign in to respond to friend requests.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can respond to friend requests.", 403)
    data = request.get_json(silent=True)
    decision = data.get("status") if isinstance(data, dict) else None
    if decision not in ("accepted", "rejected"):
        return json_error("Choose whether to accept or decline the invitation.", 400)

    user_id = session["user_id"]
    if student_id == user_id:
        return json_error("You cannot respond to your own invitation.", 400)
    user_a, user_b = sorted((user_id, student_id))
    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT requested_by, status FROM friendships "
                    "WHERE user_id_a = %s AND user_id_b = %s FOR UPDATE",
                    (user_a, user_b),
                )
                relationship = cursor.fetchone()
                if (
                    not relationship
                    or relationship["status"] != "pending"
                    or relationship["requested_by"] == user_id
                ):
                    return json_error("There is no incoming invitation to respond to.", 404)
                cursor.execute(
                    "UPDATE friendships SET status = %s "
                    "WHERE user_id_a = %s AND user_id_b = %s",
                    (decision, user_a, user_b),
                )
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while responding to a friend request")
        return json_error("Could not update this invitation in python_app.", 503)

    return jsonify({"status": decision})


@app.get("/api/friends")
def active_friends():
    if "user_id" not in session:
        return json_error("Sign in to view your friends.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can view friends.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT u.user_id, u.full_name AS username, p.course_of_study "
                    "FROM friendships AS f "
                    "JOIN users AS u ON u.user_id = CASE "
                    "WHEN f.user_id_a = %s THEN f.user_id_b ELSE f.user_id_a END "
                    "JOIN user_roles AS ur ON ur.user_id = u.user_id "
                    "JOIN roles AS r ON r.role_id = ur.role_id "
                    "LEFT JOIN profiles AS p ON p.user_id = u.user_id "
                    "WHERE (f.user_id_a = %s OR f.user_id_b = %s) "
                    "AND f.status = 'accepted' AND u.account_status = 'active' "
                    "AND r.role_key = 'student' "
                    "ORDER BY u.full_name, u.user_id",
                    (session["user_id"], session["user_id"], session["user_id"]),
                )
                friends = cursor.fetchall()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading accepted friendships")
        return json_error("Could not load your friends from python_app.", 503)

    return jsonify({"friends": friends})


def is_accepted_friendship(cursor, user_id, friend_id):
    user_a, user_b = sorted((user_id, friend_id))
    cursor.execute(
        "SELECT 1 FROM users AS u "
        "JOIN user_roles AS ur ON ur.user_id = u.user_id "
        "JOIN roles AS r ON r.role_id = ur.role_id "
        "WHERE u.user_id = %s AND u.account_status = 'active' "
        "AND r.role_key = 'student' AND EXISTS ("
        "SELECT 1 FROM friendships AS f WHERE f.user_id_a = %s "
        "AND f.user_id_b = %s AND f.status = 'accepted') "
        "AND EXISTS (SELECT 1 FROM users AS active_account "
        "JOIN user_roles AS current_roles ON current_roles.user_id = active_account.user_id "
        "JOIN roles AS active_role ON active_role.role_id = current_roles.role_id "
        "WHERE active_account.user_id = %s AND active_account.account_status = 'active' "
        "AND active_role.role_key = 'student') LIMIT 1",
        (friend_id, user_a, user_b, user_id),
    )
    return cursor.fetchone() is not None


def is_valid_encrypted_payload(payload, sender_id, recipient_id):
    if not isinstance(payload, dict) or set(payload) != {
        "v", "sender_id", "recipient_id", "iv", "ciphertext", "keys", "signature"
    }:
        return False
    if type(payload.get("v")) is not int or payload["v"] != 1:
        return False
    if type(payload.get("sender_id")) is not int or type(payload.get("recipient_id")) is not int:
        return False
    if payload.get("sender_id") != sender_id or payload.get("recipient_id") != recipient_id:
        return False
    keys = payload.get("keys")
    if not isinstance(keys, dict) or set(keys) != {str(sender_id), str(recipient_id)}:
        return False
    try:
        ciphertext = base64.b64decode(payload["ciphertext"], validate=True)
        nonce = base64.b64decode(payload["iv"], validate=True)
        signature = base64.b64decode(payload["signature"], validate=True)
        wrapped_keys = [
            base64.b64decode(keys[str(sender_id)], validate=True),
            base64.b64decode(keys[str(recipient_id)], validate=True),
        ]
    except (KeyError, TypeError, ValueError, binascii.Error):
        return False
    return (
        16 <= len(ciphertext) <= 12000
        and len(nonce) == 12
        and len(signature) == 64
        and all(len(wrapped_key) == 256 for wrapped_key in wrapped_keys)
        and len(json.dumps(payload, separators=(",", ":"))) <= 24000
    )


@app.get("/api/encryption-key")
def get_encryption_key():
    if "user_id" not in session:
        return json_error("Sign in to load your encryption key.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can use private messaging.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT public_key FROM user_encryption_keys WHERE user_id = %s LIMIT 1",
                    (session["user_id"],),
                )
                key = cursor.fetchone()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading the student's encryption key")
        return json_error("Could not load your encryption key from python_app.", 503)

    response = jsonify({"public_key": key["public_key"] if key else None})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.put("/api/encryption-key")
def register_encryption_key():
    if "user_id" not in session:
        return json_error("Sign in to register your encryption key.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can use private messaging.", 403)
    data = request.get_json(silent=True)
    public_key = data.get("public_key") if isinstance(data, dict) else None
    if not isinstance(public_key, str) or len(public_key) > 2048:
        return json_error("Send a valid public encryption key.", 400)
    try:
        key_bundle = json.loads(public_key)
        encryption_key = base64.b64decode(key_bundle["encryption"], validate=True)
        signing_key = base64.b64decode(key_bundle["signing"], validate=True)
        if (
            key_bundle.get("v") != 1
            or set(key_bundle) != {"v", "encryption", "signing"}
            or not 256 <= len(encryption_key) <= 512
            or not 64 <= len(signing_key) <= 160
        ):
            raise ValueError("Invalid public key bundle.")
    except (KeyError, TypeError, ValueError, binascii.Error, json.JSONDecodeError):
        return json_error("Send a valid public encryption key.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "INSERT IGNORE INTO user_encryption_keys (user_id, public_key) "
                    "VALUES (%s, %s)",
                    (session["user_id"], public_key),
                )
                connection.commit()
                cursor.execute(
                    "SELECT public_key FROM user_encryption_keys WHERE user_id = %s",
                    (session["user_id"],),
                )
                existing = cursor.fetchone()
                if not existing or existing["public_key"] != public_key:
                    return json_error(
                        "This account already has an encryption key on another browser. "
                        "The key cannot be replaced without losing access to its messages.",
                        409,
                    )
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while registering the student's encryption key")
        return json_error("Could not register your encryption key in python_app.", 503)

    response = jsonify({"public_key": public_key})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/friends/<int:friend_id>/encryption-key")
def get_friend_encryption_key(friend_id):
    if "user_id" not in session:
        return json_error("Sign in to load a friend's encryption key.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can use private messaging.", 403)
    user_id = session["user_id"]
    if friend_id == user_id:
        return json_error("You cannot load your own key as a friend's key.", 400)
    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if not is_accepted_friendship(cursor, user_id, friend_id):
                    return json_error("Encryption keys are available to accepted friends only.", 403)
                cursor.execute(
                    "SELECT public_key FROM user_encryption_keys "
                    "WHERE user_id = %s LIMIT 1",
                    (friend_id,),
                )
                key = cursor.fetchone()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading a friend's encryption key")
        return json_error("Could not load your friend's encryption key from python_app.", 503)

    response = jsonify({"public_key": key["public_key"] if key else None})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/friends/<int:friend_id>/messages")
def get_private_messages(friend_id):
    if "user_id" not in session:
        return json_error("Sign in to view messages.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can view messages.", 403)
    user_id = session["user_id"]
    if friend_id == user_id:
        return json_error("You cannot message your own account.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if not is_accepted_friendship(cursor, user_id, friend_id):
                    return json_error("You can message accepted friends only.", 403)
                cursor.execute(
                    "SELECT message_id, sender_id, recipient_id, encrypted_payload, created_at "
                    "FROM private_messages WHERE "
                    "(sender_id = %s AND recipient_id = %s) OR "
                    "(sender_id = %s AND recipient_id = %s) "
                    "ORDER BY message_id DESC LIMIT 100",
                    (user_id, friend_id, friend_id, user_id),
                )
                messages = list(reversed(cursor.fetchall()))
                for message in messages:
                    if isinstance(message.get("created_at"), datetime):
                        message["created_at"] = message["created_at"].isoformat(sep=" ")
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading private messages")
        return json_error("Could not load messages from python_app.", 503)

    response = jsonify({"messages": messages})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/friends/<int:friend_id>/messages")
def send_private_message(friend_id):
    if "user_id" not in session:
        return json_error("Sign in to send messages.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can send messages.", 403)
    user_id = session["user_id"]
    if friend_id == user_id:
        return json_error("You cannot message your own account.", 400)
    data = request.get_json(silent=True)
    encrypted_payload = data.get("encrypted_payload") if isinstance(data, dict) else None
    attachment_id = data.get("attachment_id") if isinstance(data, dict) else None
    if not is_valid_encrypted_payload(encrypted_payload, user_id, friend_id):
        return json_error("Send a valid encrypted message for this conversation.", 400)
    if attachment_id is not None and (
        not isinstance(attachment_id, str)
        or not re.fullmatch(r"[a-f0-9]{32}", attachment_id)
    ):
        return json_error("The encrypted attachment identifier is invalid.", 400)
    serialized_payload = json.dumps(encrypted_payload, separators=(",", ":"))

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if not is_accepted_friendship(cursor, user_id, friend_id):
                    return json_error("You can message accepted friends only.", 403)
                if attachment_id:
                    cursor.execute(
                        "SELECT attachment_id FROM private_message_attachments "
                        "WHERE attachment_id = %s AND sender_id = %s "
                        "AND recipient_id = %s AND message_id IS NULL FOR UPDATE",
                        (attachment_id, user_id, friend_id),
                    )
                    if not cursor.fetchone():
                        return json_error("The encrypted attachment is unavailable.", 404)
                cursor.execute(
                    "INSERT INTO private_messages (sender_id, recipient_id, encrypted_payload) "
                    "VALUES (%s, %s, %s)",
                    (user_id, friend_id, serialized_payload),
                )
                message_id = cursor.lastrowid
                if attachment_id:
                    cursor.execute(
                        "UPDATE private_message_attachments SET message_id = %s "
                        "WHERE attachment_id = %s AND sender_id = %s "
                        "AND recipient_id = %s AND message_id IS NULL",
                        (message_id, attachment_id, user_id, friend_id),
                    )
                    if cursor.rowcount != 1:
                        connection.rollback()
                        return json_error("The encrypted attachment is unavailable.", 404)
                connection.commit()
                cursor.execute(
                    "SELECT message_id, sender_id, recipient_id, encrypted_payload, created_at "
                    "FROM private_messages WHERE message_id = %s",
                    (message_id,),
                )
                message = cursor.fetchone()
                if message and isinstance(message.get("created_at"), datetime):
                    message["created_at"] = message["created_at"].isoformat()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while sending a private message")
        return json_error("Could not send this message to python_app.", 503)

    response = jsonify({"message": message})
    response.status_code = 201
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/friends/<int:friend_id>/attachments")
def upload_private_attachment(friend_id):
    if "user_id" not in session:
        return json_error("Sign in to share files.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can share files.", 403)
    user_id = session["user_id"]
    if friend_id == user_id:
        return json_error("You cannot share files with your own account.", 400)
    if request.mimetype != "application/octet-stream":
        return json_error("Send the encrypted file as binary data.", 400)

    encrypted_file = request.get_data(cache=False)
    if len(encrypted_file) < 16:
        return json_error("The encrypted file is incomplete.", 400)
    if len(encrypted_file) > MAX_ENCRYPTED_PRIVATE_ATTACHMENT_BYTES:
        return json_error("Encrypted files must be 10 MB or smaller.", 413)

    attachment_id = uuid.uuid4().hex
    storage_name = uuid.uuid4().hex
    try:
        PRIVATE_MESSAGE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (PRIVATE_MESSAGE_UPLOAD_DIR / storage_name).write_bytes(encrypted_file)
    except OSError:
        app.logger.exception("Could not save an encrypted private-message attachment")
        return json_error("Could not save the encrypted file.", 500)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if not is_accepted_friendship(cursor, user_id, friend_id):
                    (PRIVATE_MESSAGE_UPLOAD_DIR / storage_name).unlink(missing_ok=True)
                    return json_error("You can share files with accepted friends only.", 403)
                cursor.execute(
                    "INSERT INTO private_message_attachments "
                    "(attachment_id, sender_id, recipient_id, storage_name, encrypted_size) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (attachment_id, user_id, friend_id, storage_name, len(encrypted_file)),
                )
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        (PRIVATE_MESSAGE_UPLOAD_DIR / storage_name).unlink(missing_ok=True)
        app.logger.exception("MySQL error while recording an encrypted attachment")
        return json_error("Could not save the encrypted file to python_app.", 503)

    response = jsonify({"attachment_id": attachment_id})
    response.status_code = 201
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/friends/<int:friend_id>/attachments/<attachment_id>")
def download_private_attachment(friend_id, attachment_id):
    if "user_id" not in session:
        return json_error("Sign in to download shared files.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can download shared files.", 403)
    user_id = session["user_id"]
    if (
        friend_id == user_id
        or not re.fullmatch(r"[a-f0-9]{32}", attachment_id)
    ):
        return json_error("The encrypted attachment was not found.", 404)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if not is_accepted_friendship(cursor, user_id, friend_id):
                    return json_error("You can download files from accepted friends only.", 403)
                cursor.execute(
                    "SELECT a.storage_name FROM private_message_attachments AS a "
                    "JOIN private_messages AS m ON m.message_id = a.message_id "
                    "WHERE a.attachment_id = %s AND a.message_id IS NOT NULL "
                    "AND ((a.sender_id = %s AND a.recipient_id = %s) "
                    "OR (a.sender_id = %s AND a.recipient_id = %s)) "
                    "AND ((m.sender_id = %s AND m.recipient_id = %s) "
                    "OR (m.sender_id = %s AND m.recipient_id = %s)) LIMIT 1",
                    (
                        attachment_id,
                        user_id,
                        friend_id,
                        friend_id,
                        user_id,
                        user_id,
                        friend_id,
                        friend_id,
                        user_id,
                    ),
                )
                attachment = cursor.fetchone()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading an encrypted attachment")
        return json_error("Could not load the encrypted file from python_app.", 503)

    if not attachment or not re.fullmatch(r"[a-f0-9]{32}", attachment["storage_name"]):
        return json_error("The encrypted file was not found.", 404)
    file_path = PRIVATE_MESSAGE_UPLOAD_DIR / attachment["storage_name"]
    if not file_path.is_file():
        return json_error("The encrypted file is unavailable.", 404)
    response = send_from_directory(
        PRIVATE_MESSAGE_UPLOAD_DIR,
        attachment["storage_name"],
        mimetype="application/octet-stream",
        as_attachment=False,
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.delete("/api/friends/<int:friend_id>/attachments/<attachment_id>")
def delete_unshared_private_attachment(friend_id, attachment_id):
    if "user_id" not in session:
        return json_error("Sign in to remove a shared file.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can remove shared files.", 403)
    if not re.fullmatch(r"[a-f0-9]{32}", attachment_id):
        return json_error("The encrypted attachment was not found.", 404)

    storage_name = None
    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT storage_name FROM private_message_attachments "
                    "WHERE attachment_id = %s AND sender_id = %s "
                    "AND recipient_id = %s AND message_id IS NULL FOR UPDATE",
                    (attachment_id, session["user_id"], friend_id),
                )
                attachment = cursor.fetchone()
                if not attachment:
                    return json_error("The encrypted attachment was not found.", 404)
                storage_name = attachment["storage_name"]
                cursor.execute(
                    "DELETE FROM private_message_attachments WHERE attachment_id = %s",
                    (attachment_id,),
                )
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while removing an unused encrypted attachment")
        return json_error("Could not remove the encrypted file from python_app.", 503)

    if storage_name and re.fullmatch(r"[a-f0-9]{32}", storage_name):
        (PRIVATE_MESSAGE_UPLOAD_DIR / storage_name).unlink(missing_ok=True)
    return jsonify({"deleted": True})


@app.get("/api/communities")
def active_communities():
    if "user_id" not in session:
        return json_error("Sign in to view communities.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can view communities.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT c.community_id, c.name, c.description, "
                    "c.community_group, c.community_category, "
                    "c.community_category AS course_name, "
                    "(SELECT mine.member_role FROM community_members AS mine "
                    "WHERE mine.community_id = c.community_id AND mine.user_id = %s "
                    "AND mine.status = 'active' LIMIT 1) AS member_role, "
                    "(SELECT COUNT(*) FROM community_members AS members "
                    "WHERE members.community_id = c.community_id AND members.status = 'active') "
                    "AS member_count, "
                    "EXISTS (SELECT 1 FROM community_members AS mine "
                    "WHERE mine.community_id = c.community_id AND mine.user_id = %s "
                    "AND mine.status = 'active') AS is_member "
                    "FROM communities AS c "
                    "WHERE c.status = 'active' "
                    "AND (c.visibility = 'public' OR EXISTS ("
                    "SELECT 1 FROM community_members AS mine "
                    "WHERE mine.community_id = c.community_id AND mine.user_id = %s "
                    "AND mine.status = 'active')) "
                    "ORDER BY c.name, c.community_id",
                    (session["user_id"], session["user_id"], session["user_id"]),
                )
                communities = cursor.fetchall()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading communities")
        return json_error("Could not load communities from python_app.", 503)

    return jsonify({"communities": communities})


@app.post("/api/communities")
def create_community():
    if "user_id" not in session:
        return json_error("Sign in to create a community.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can create communities.", 403)
    if not request.is_json:
        return json_error("Send community details as JSON.", 400)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return json_error("Send valid community details.", 400)

    name = data.get("name")
    group = data.get("group", "IT Communities")
    category = data.get("category")
    description = data.get("description", "")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 180:
        return json_error("Enter a community name up to 180 characters.", 400)
    if not isinstance(group, str) or group not in COMMUNITY_GROUP_CATEGORIES:
        return json_error("Choose a valid community group.", 400)
    if category not in COMMUNITY_GROUP_CATEGORIES[group]:
        return json_error(f"Choose a valid {group} topic.", 400)
    if not isinstance(description, str) or len(description.strip()) > 1000:
        return json_error("The description must be 1000 characters or fewer.", 400)

    name = name.strip()
    description = description.strip() or None
    try:
        with database_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "INSERT INTO communities "
                    "(course_id, created_by, name, description, community_group, community_category, "
                    "visibility, status) "
                    "VALUES (NULL, %s, %s, %s, %s, %s, 'public', 'active')",
                    (session["user_id"], name, description, group, category),
                )
                community_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO community_members "
                    "(community_id, user_id, member_role, status) "
                    "VALUES (%s, %s, 'owner', 'active')",
                    (community_id, session["user_id"]),
                )
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while creating a community")
        return json_error("Could not create the community in python_app.", 503)

    return jsonify(
        {
            "community": {
                "community_id": community_id,
                "name": name,
                "description": description,
                "community_group": group,
                "community_category": category,
                "course_name": category,
                "member_count": 1,
                "is_member": True,
            }
        }
    ), 201


@app.post("/api/communities/<int:community_id>/join")
def join_community(community_id):
    if "user_id" not in session:
        return json_error("Sign in to join a community.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can join communities.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT visibility, status FROM communities "
                    "WHERE community_id = %s LIMIT 1",
                    (community_id,),
                )
                community = cursor.fetchone()
                if not community or community["status"] != "active":
                    return json_error("This community is unavailable.", 404)
                if community["visibility"] != "public":
                    return json_error("This community is not open to new members.", 403)

                cursor.execute(
                    "SELECT status FROM community_members "
                    "WHERE community_id = %s AND user_id = %s FOR UPDATE",
                    (community_id, session["user_id"]),
                )
                membership = cursor.fetchone()
                if membership and membership["status"] == "banned":
                    return json_error("You cannot join this community.", 403)

                cursor.execute(
                    "INSERT INTO community_members (community_id, user_id, status) "
                    "VALUES (%s, %s, 'active') "
                    "ON DUPLICATE KEY UPDATE status = 'active'",
                    (community_id, session["user_id"]),
                )
                cursor.execute(
                    "SELECT COUNT(*) AS member_count FROM community_members "
                    "WHERE community_id = %s AND status = 'active'",
                    (community_id,),
                )
                member_count = cursor.fetchone()["member_count"]
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while joining a community")
        return json_error("Could not join the community in python_app.", 503)

    return jsonify({"member_count": member_count, "is_member": True})


@app.get("/api/communities/<int:community_id>/messages")
def get_community_messages(community_id):
    if "user_id" not in session:
        return json_error("Sign in to view community messages.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can view community messages.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT members.member_role FROM community_members AS members "
                    "JOIN communities AS community ON community.community_id = members.community_id "
                    "AND community.status = 'active' "
                    "WHERE members.community_id = %s AND members.user_id = %s "
                    "AND members.status = 'active' "
                    "LIMIT 1",
                    (community_id, session["user_id"]),
                )
                membership = cursor.fetchone()
                if not membership:
                    return json_error("Join this community to view its messages.", 403)

                cursor.execute(
                    "SELECT m.message_id, m.community_id, m.author_id, "
                    "u.full_name AS author_name, m.content, m.message_type, "
                    "m.is_highlighted, m.is_pinned, "
                    "m.pinned_by, m.pinned_at, m.created_at "
                    "FROM community_messages AS m "
                    "JOIN users AS u ON u.user_id = m.author_id "
                    "WHERE m.community_id = %s AND (m.is_pinned = TRUE OR "
                    "m.message_id >= COALESCE(("
                    "SELECT MIN(recent.message_id) FROM ("
                    "SELECT message_id FROM community_messages "
                    "WHERE community_id = %s ORDER BY message_id DESC LIMIT 100"
                    ") AS recent), 0)) "
                    "ORDER BY m.is_pinned DESC, m.message_id ASC",
                    (community_id, community_id),
                )
                messages = cursor.fetchall()
                for message in messages:
                    message["can_manage"] = (
                        message["author_id"] == session["user_id"]
                        or membership["member_role"] in ("owner", "moderator")
                    )
                    message["is_mine"] = message["author_id"] == session["user_id"]
                    for field in ("pinned_at", "created_at"):
                        if isinstance(message.get(field), datetime):
                            message[field] = message[field].isoformat(sep=" ")
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading community messages")
        return json_error("Could not load community messages from python_app.", 503)

    response = jsonify({"messages": messages})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/communities/<int:community_id>/messages")
def send_community_message(community_id):
    if "user_id" not in session:
        return json_error("Sign in to send community messages.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can send community messages.", 403)
    if not request.is_json:
        return json_error("Send the message as JSON.", 400)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return json_error("Send a valid community message.", 400)
    content = data.get("content")
    message_type = data.get("message_type", "message")
    if not isinstance(content, str) or not content.strip() or len(content.strip()) > 2000:
        return json_error("Enter a message up to 2000 characters.", 400)
    if message_type not in ("message", "announcement"):
        return json_error("Choose a valid community message type.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT members.member_role FROM community_members AS members "
                    "JOIN communities AS community ON community.community_id = members.community_id "
                    "AND community.status = 'active' "
                    "WHERE members.community_id = %s AND members.user_id = %s "
                    "AND members.status = 'active' "
                    "LIMIT 1",
                    (community_id, session["user_id"]),
                )
                if not cursor.fetchone():
                    return json_error("Join this community to send messages.", 403)

                cursor.execute(
                    "INSERT INTO community_messages "
                    "(community_id, author_id, content, message_type) "
                    "VALUES (%s, %s, %s, %s)",
                    (community_id, session["user_id"], content.strip(), message_type),
                )
                message_id = cursor.lastrowid
                connection.commit()
                cursor.execute(
                    "SELECT m.message_id, m.community_id, m.author_id, "
                    "u.full_name AS author_name, m.content, m.message_type, "
                    "m.is_highlighted, m.is_pinned, "
                    "m.pinned_by, m.pinned_at, m.created_at "
                    "FROM community_messages AS m "
                    "JOIN users AS u ON u.user_id = m.author_id "
                    "WHERE m.message_id = %s",
                    (message_id,),
                )
                message = cursor.fetchone()
                message["can_manage"] = True
                for field in ("pinned_at", "created_at"):
                    if isinstance(message.get(field), datetime):
                        message[field] = message[field].isoformat(sep=" ")
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while sending a community message")
        return json_error("Could not send the community message to python_app.", 503)

    response = jsonify({"message": message})
    response.headers["Cache-Control"] = "no-store"
    return response, 201


@app.patch("/api/communities/<int:community_id>/messages/<int:message_id>")
def update_community_message(community_id, message_id):
    if "user_id" not in session:
        return json_error("Sign in to update community messages.", 401)
    if session.get("role") != "student":
        return json_error("Only student accounts can update community messages.", 403)
    if not request.is_json:
        return json_error("Send message changes as JSON.", 400)

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return json_error("Send valid message changes.", 400)
    allowed_fields = {"is_pinned", "is_highlighted"}
    if not set(data).issubset(allowed_fields) or not data:
        return json_error("Only pin and highlight settings can be changed.", 400)
    if any(not isinstance(value, bool) for value in data.values()):
        return json_error("Pin and highlight settings must be true or false.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT members.member_role FROM community_members AS members "
                    "JOIN communities AS community ON community.community_id = members.community_id "
                    "AND community.status = 'active' "
                    "WHERE members.community_id = %s AND members.user_id = %s "
                    "AND members.status = 'active' "
                    "LIMIT 1",
                    (community_id, session["user_id"]),
                )
                membership = cursor.fetchone()
                if not membership:
                    return json_error("Join this community to update its messages.", 403)

                cursor.execute(
                    "SELECT author_id FROM community_messages "
                    "WHERE message_id = %s AND community_id = %s FOR UPDATE",
                    (message_id, community_id),
                )
                message = cursor.fetchone()
                if not message:
                    return json_error("The community message was not found.", 404)
                can_manage = (
                    message["author_id"] == session["user_id"]
                    or membership["member_role"] in ("owner", "moderator")
                )
                if not can_manage:
                    return json_error("You can update only your own messages.", 403)

                assignments = []
                parameters = []
                if "is_highlighted" in data:
                    assignments.append("is_highlighted = %s")
                    parameters.append(data["is_highlighted"])
                if "is_pinned" in data:
                    if data["is_pinned"]:
                        assignments.extend((
                            "is_pinned = TRUE",
                            "pinned_by = %s",
                            "pinned_at = CURRENT_TIMESTAMP",
                        ))
                        parameters.append(session["user_id"])
                    else:
                        assignments.extend((
                            "is_pinned = FALSE",
                            "pinned_by = NULL",
                            "pinned_at = NULL",
                        ))
                parameters.append(message_id)
                cursor.execute(
                    "UPDATE community_messages SET "
                    + ", ".join(assignments)
                    + " WHERE message_id = %s",
                    tuple(parameters),
                )
                connection.commit()
                cursor.execute(
                    "SELECT m.message_id, m.community_id, m.author_id, "
                    "u.full_name AS author_name, m.content, m.message_type, "
                    "m.is_highlighted, m.is_pinned, "
                    "m.pinned_by, m.pinned_at, m.created_at "
                    "FROM community_messages AS m "
                    "JOIN users AS u ON u.user_id = m.author_id "
                    "WHERE m.message_id = %s",
                    (message_id,),
                )
                updated_message = cursor.fetchone()
                updated_message["can_manage"] = True
                updated_message["is_mine"] = updated_message["author_id"] == session["user_id"]
                for field in ("pinned_at", "created_at"):
                    if isinstance(updated_message.get(field), datetime):
                        updated_message[field] = updated_message[field].isoformat(sep=" ")
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while updating a community message")
        return json_error("Could not update the community message in python_app.", 503)

    response = jsonify({"message": updated_message})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/AdminPage.html")
def admin_dashboard():
    if "user_id" not in session:
        return redirect("/indext.html?tab=login")
    if session.get("role") != "admin":
        return redirect("/dashboard.html")
    return send_from_directory(BASE_DIR, "AdminPage.html")


@app.get("/api/admin/resources/<int:resource_id>/file")
def pending_resource_file(resource_id):
    if "user_id" not in session or session.get("role") != "admin":
        return json_error("Administrator access is required.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                admin_user = active_admin(cursor, session["user_id"])
                if not admin_user:
                    return json_error("Administrator access is no longer active.", 403)
                cursor.execute(
                    "SELECT title, file_url FROM resources "
                    "WHERE resource_id = %s AND status = 'pending' LIMIT 1",
                    (resource_id,),
                )
                resource = cursor.fetchone()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading a pending resource file")
        return json_error("Could not load the resource from python_app.", 503)

    if not resource or not is_stored_resource_file(resource["file_url"]):
        return json_error("This pending resource file is unavailable.", 404)
    file_name = Path(resource["file_url"]).name
    response = send_from_directory(
        RESOURCE_UPLOAD_DIR,
        file_name,
        as_attachment=True,
        download_name=resource_download_name(resource["title"], file_name),
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.post("/api/admin/resources/<int:resource_id>/review")
def review_resource(resource_id):
    if "user_id" not in session or session.get("role") != "admin":
        return json_error("Administrator access is required.", 403)
    if not request.is_json:
        return json_error("Send a review decision as JSON.", 400)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("status") not in {"approved", "rejected"}:
        return json_error("Choose approve or reject for this resource.", 400)

    status = payload["status"]
    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                admin_user = active_admin(cursor, session["user_id"])
                if not admin_user:
                    return json_error("Administrator access is no longer active.", 403)
                cursor.execute(
                    "SELECT status FROM resources WHERE resource_id = %s FOR UPDATE",
                    (resource_id,),
                )
                resource = cursor.fetchone()
                if not resource:
                    return json_error("This resource is unavailable.", 404)
                if resource["status"] != "pending":
                    return json_error("This resource has already been reviewed.", 409)
                cursor.execute(
                    "UPDATE resources SET status = %s, reviewed_by = %s, "
                    "reviewed_at = CURRENT_TIMESTAMP WHERE resource_id = %s",
                    (status, session["user_id"], resource_id),
                )
                record_admin_audit(
                    cursor,
                    session["user_id"],
                    f"resource.{status}",
                    "resource",
                    resource_id,
                    f"Resource review status set to {status}.",
                )
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while reviewing a resource")
        return json_error("Could not save the resource review in python_app.", 503)

    return jsonify({"resource_id": resource_id, "status": status})


@app.get("/api/admin/audit-logs")
def admin_audit_logs():
    if "user_id" not in session or session.get("role") != "admin":
        return json_error("Administrator access is required.", 403)

    limit = request.args.get("limit", default=50, type=int)
    if limit is None or not 1 <= limit <= 100:
        return json_error("Choose an audit-log limit between 1 and 100.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                admin_user = active_admin(cursor, session["user_id"])
                if not admin_user:
                    return json_error("Administrator access is no longer active.", 403)
                cursor.execute(
                    "SELECT audit.audit_id, audit.admin_user_id, "
                    "admin.full_name AS admin_name, audit.action, audit.target_type, "
                    "audit.target_id, audit.details, audit.created_at "
                    "FROM admin_audit_log AS audit "
                    "JOIN users AS admin ON admin.user_id = audit.admin_user_id "
                    "ORDER BY audit.created_at DESC, audit.audit_id DESC LIMIT %s",
                    (limit,),
                )
                audit_logs = cursor.fetchall()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading admin audit logs")
        return json_error("Could not load admin audit logs from python_app.", 503)

    response = jsonify({"audit_logs": audit_logs})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/admin/course-materials")
def admin_course_materials():
    if "user_id" not in session or session.get("role") != "admin":
        return json_error("Administrator access is required.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if not active_admin(cursor, session["user_id"]):
                    return json_error("Administrator access is no longer active.", 403)
                placeholders = ", ".join(["%s"] * len(RESOURCE_CATEGORIES))
                cursor.execute(
                    "SELECT r.resource_id, r.title, r.description, r.resource_type, "
                    "r.resource_category, r.file_url, r.source_url, r.created_at, "
                    "u.full_name AS uploader_name "
                    "FROM resources AS r "
                    "JOIN users AS u ON u.user_id = r.uploaded_by "
                    f"WHERE r.status = 'approved' AND r.resource_category IN ({placeholders}) "
                    "ORDER BY r.resource_category, r.created_at DESC, r.resource_id DESC",
                    RESOURCE_CATEGORIES,
                )
                materials = cursor.fetchall()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading admin course materials")
        return json_error("Could not load course materials from python_app.", 503)

    materials_by_category = {category: [] for category in RESOURCE_CATEGORIES}
    for material in materials:
        category = material["resource_category"]
        if category not in materials_by_category:
            continue
        material["material_url"] = (
            f"/api/admin/course-materials/{material['resource_id']}/file"
            if is_stored_resource_file(material.get("file_url"))
            else material.get("source_url")
        )
        materials_by_category[category].append(material)

    categories = [
        {
            "key": "IT",
            "name": "Information Technology (IT)",
            "materials": materials_by_category["IT"],
            "material_count": len(materials_by_category["IT"]),
        },
        {
            "key": "Business Administration",
            "name": "Business Administration (BA)",
            "materials": materials_by_category["Business Administration"],
            "material_count": len(materials_by_category["Business Administration"]),
        },
    ]
    response = jsonify({"course_count": len(categories), "categories": categories})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/admin/course-materials")
def admin_add_course_material():
    if "user_id" not in session or session.get("role") != "admin":
        return json_error("Administrator access is required.", 403)

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("resource_category", "")
    resource_type = request.form.get("resource_type", "")
    upload = request.files.get("file")
    if not title or len(title) > 220:
        return json_error("Enter a material title up to 220 characters.", 400)
    if len(description) > 2000:
        return json_error("The description must be 2000 characters or fewer.", 400)
    if category not in RESOURCE_CATEGORIES:
        return json_error("Choose IT or Business Administration.", 400)
    if resource_type not in RESOURCE_TYPES:
        return json_error("Choose Notes, Articles, or Past Papers & Memos.", 400)
    if not upload or not upload.filename:
        return json_error("Choose a PDF, DOC, or DOCX file to upload.", 400)
    if not valid_resource_file(upload):
        return json_error("Upload a valid PDF, DOC, or DOCX document.", 400)

    extension = Path(upload.filename).suffix.lower()
    temporary_name = f"{secrets.token_hex(16)}{extension}"
    temporary_path = RESOURCE_UPLOAD_DIR / temporary_name
    try:
        RESOURCE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        upload.save(temporary_path)
        if temporary_path.stat().st_size > MAX_RESOURCE_UPLOAD_BYTES:
            temporary_path.unlink()
            return json_error("The uploaded file is larger than the 10 MB limit.", 413)

        with database_connection() as connection:
            cursor = connection.cursor()
            try:
                if not active_admin(cursor, session["user_id"]):
                    temporary_path.unlink(missing_ok=True)
                    return json_error("Administrator access is no longer active.", 403)
                cursor.execute(
                    "INSERT INTO resources "
                    "(course_id, uploaded_by, reviewed_by, title, description, resource_type, "
                    "resource_category, file_url, status, reviewed_at) "
                    "VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, 'approved', CURRENT_TIMESTAMP)",
                    (
                        session["user_id"],
                        session["user_id"],
                        title,
                        description or None,
                        resource_type,
                        category,
                        temporary_name,
                    ),
                )
                resource_id = cursor.lastrowid
                record_admin_audit(
                    cursor,
                    session["user_id"],
                    "course_material.added",
                    "resource",
                    resource_id,
                    f"Published {resource_type} material '{title}' in {category}.",
                )
                connection.commit()
            finally:
                cursor.close()
    except OSError:
        app.logger.exception("File system error while saving an admin course material")
        temporary_path.unlink(missing_ok=True)
        return json_error("Could not save the course material file.", 500)
    except mysql.connector.Error:
        app.logger.exception("MySQL error while publishing an admin course material")
        temporary_path.unlink(missing_ok=True)
        return json_error("Could not publish the course material in python_app.", 503)

    return jsonify(
        {"resource_id": resource_id, "status": "approved", "message": "Course material published."}
    ), 201


@app.get("/api/admin/course-materials/<int:resource_id>/file")
def admin_course_material_file(resource_id):
    if "user_id" not in session or session.get("role") != "admin":
        return json_error("Administrator access is required.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if not active_admin(cursor, session["user_id"]):
                    return json_error("Administrator access is no longer active.", 403)
                cursor.execute(
                    "SELECT title, file_url FROM resources "
                    "WHERE resource_id = %s AND status = 'approved' "
                    "AND resource_category IN (%s, %s) LIMIT 1",
                    (resource_id, *RESOURCE_CATEGORIES),
                )
                resource = cursor.fetchone()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading an admin course material file")
        return json_error("Could not load the course material from python_app.", 503)

    if not resource or not is_stored_resource_file(resource["file_url"]):
        return json_error("This course material file is unavailable.", 404)
    file_name = Path(resource["file_url"]).name
    response = send_from_directory(
        RESOURCE_UPLOAD_DIR,
        file_name,
        as_attachment=True,
        download_name=resource_download_name(resource["title"], file_name),
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.post("/api/admin/course-materials/<int:resource_id>/archive")
def admin_archive_course_material(resource_id):
    if "user_id" not in session or session.get("role") != "admin":
        return json_error("Administrator access is required.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if not active_admin(cursor, session["user_id"]):
                    return json_error("Administrator access is no longer active.", 403)
                cursor.execute(
                    "SELECT title, resource_category, status FROM resources "
                    "WHERE resource_id = %s FOR UPDATE",
                    (resource_id,),
                )
                material = cursor.fetchone()
                if not material or material["resource_category"] not in RESOURCE_CATEGORIES:
                    return json_error("This course material is unavailable.", 404)
                if material["status"] != "approved":
                    return json_error("This course material is already unavailable.", 409)
                cursor.execute(
                    "UPDATE resources SET status = 'archived' "
                    "WHERE resource_id = %s AND status = 'approved'",
                    (resource_id,),
                )
                record_admin_audit(
                    cursor,
                    session["user_id"],
                    "course_material.archived",
                    "resource",
                    resource_id,
                    f"Archived material '{material['title']}' from {material['resource_category']}.",
                )
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while archiving an admin course material")
        return json_error("Could not remove the course material from python_app.", 503)

    return jsonify({"resource_id": resource_id, "status": "archived"})


@app.post("/api/student/session-heartbeat")
def student_session_heartbeat():
    if "user_id" not in session or session.get("role") != "student":
        return json_error("Student sign-in is required.", 401)
    activity_id = session.get("student_activity_id")

    refreshed_activity_id = None
    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if not activity_id:
                    cursor.execute(
                        "INSERT INTO student_login_sessions (user_id) VALUES (%s)",
                        (session["user_id"],),
                    )
                    refreshed_activity_id = cursor.lastrowid
                else:
                    cursor.execute(
                        "SELECT last_seen_at, ended_at, CURRENT_TIMESTAMP AS database_now "
                        "FROM student_login_sessions "
                        "WHERE activity_id = %s AND user_id = %s FOR UPDATE",
                        (activity_id, session["user_id"]),
                    )
                    activity = cursor.fetchone()
                    if not activity or activity["ended_at"] is not None:
                        return json_error("This login session is no longer active.", 409)

                    if activity["last_seen_at"] < (
                        activity["database_now"] - timedelta(seconds=STUDENT_SESSION_GRACE_SECONDS)
                    ):
                        cursor.execute(
                            "UPDATE student_login_sessions SET ended_at = "
                            "DATE_ADD(last_seen_at, INTERVAL %s SECOND) "
                            "WHERE activity_id = %s AND user_id = %s AND ended_at IS NULL",
                            (STUDENT_SESSION_GRACE_SECONDS, activity_id, session["user_id"]),
                        )
                        cursor.execute(
                            "INSERT INTO student_login_sessions (user_id) VALUES (%s)",
                            (session["user_id"],),
                        )
                        refreshed_activity_id = cursor.lastrowid
                    else:
                        cursor.execute(
                            "UPDATE student_login_sessions SET last_seen_at = CURRENT_TIMESTAMP "
                            "WHERE activity_id = %s AND user_id = %s AND ended_at IS NULL",
                            (activity_id, session["user_id"]),
                        )
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while recording a student session heartbeat")
        return json_error("Could not record student session activity in python_app.", 503)

    if refreshed_activity_id:
        session["student_activity_id"] = refreshed_activity_id
    response = jsonify({"status": "active"})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/admin/student-activity")
def admin_student_activity():
    if "user_id" not in session or session.get("role") != "admin":
        return json_error("Administrator access is required.", 403)

    month_value = request.args.get("month", datetime.now().strftime("%Y-%m"))
    if not re.fullmatch(r"\d{4}-\d{2}", month_value):
        return json_error("Choose a month in YYYY-MM format.", 400)
    try:
        month_start = datetime.strptime(month_value, "%Y-%m")
    except ValueError:
        return json_error("Choose a valid month.", 400)
    next_month = (
        month_start.replace(year=month_start.year + 1, month=1)
        if month_start.month == 12
        else month_start.replace(month=month_start.month + 1)
    )
    days_in_month = (next_month - timedelta(days=1)).day

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if not active_admin(cursor, session["user_id"]):
                    return json_error("Administrator access is no longer active.", 403)

                cursor.execute(
                    "SELECT tracking_started_at FROM student_activity_tracking "
                    "WHERE tracking_id = 1"
                )
                tracking = cursor.fetchone()
                if not tracking:
                    app.logger.error("Student activity tracking migration has not been applied")
                    return json_error("Student activity tracking is not configured.", 503)
                tracking_started_at = tracking["tracking_started_at"]

                cursor.execute(
                    "SELECT u.user_id, u.full_name, u.email, u.account_status "
                    "FROM users AS u "
                    "JOIN user_roles AS ur ON ur.user_id = u.user_id "
                    "JOIN roles AS r ON r.role_id = ur.role_id "
                    "WHERE u.account_status IN ('active', 'suspended') "
                    "AND r.role_key = 'student' "
                    "ORDER BY u.full_name, u.user_id"
                )
                students = cursor.fetchall()
                cursor.execute(
                    "SELECT s.user_id, s.started_at, "
                    "COALESCE(s.ended_at, LEAST(CURRENT_TIMESTAMP, "
                    "DATE_ADD(s.last_seen_at, INTERVAL %s SECOND))) AS session_end "
                    "FROM student_login_sessions AS s "
                    "JOIN users AS u ON u.user_id = s.user_id "
                    "JOIN user_roles AS ur ON ur.user_id = u.user_id "
                    "JOIN roles AS r ON r.role_id = ur.role_id "
                    "WHERE u.account_status = 'active' AND r.role_key = 'student' "
                    "AND s.started_at < %s AND COALESCE(s.ended_at, LEAST(CURRENT_TIMESTAMP, "
                    "DATE_ADD(s.last_seen_at, INTERVAL %s SECOND))) > %s",
                    (
                        STUDENT_SESSION_GRACE_SECONDS,
                        next_month,
                        STUDENT_SESSION_GRACE_SECONDS,
                        month_start,
                    ),
                )
                activities = cursor.fetchall()
            finally:
                cursor.close()
    except mysql.connector.Error as error:
        app.logger.exception("MySQL error while loading student login activity")
        if error.errno == 1146:
            return json_error(
                "Student activity tables are missing. Run database/11_student_login_activity.sql, "
                "then reload this report.",
                503,
            )
        return json_error("Could not load student login activity from python_app.", 503)

    active_students = [
        student for student in students
        if student["account_status"] == "active"
    ]
    daily_seconds = {
        student["user_id"]: [0] * days_in_month
        for student in active_students
    }
    intervals_by_student = {
        student["user_id"]: []
        for student in active_students
    }
    for activity in activities:
        start = max(activity["started_at"], month_start, tracking_started_at)
        end = min(activity["session_end"], next_month)
        if start < end:
            intervals_by_student[activity["user_id"]].append((start, end))

    for user_id, intervals in intervals_by_student.items():
        merged_start = None
        merged_end = None
        for start, end in sorted(intervals):
            if merged_end is not None and start <= merged_end:
                merged_end = max(merged_end, end)
                continue
            if merged_start is not None:
                add_daily_activity_seconds(daily_seconds[user_id], merged_start, merged_end)
            merged_start, merged_end = start, end
        if merged_start is not None:
            add_daily_activity_seconds(daily_seconds[user_id], merged_start, merged_end)

    tracking_start_date = tracking_started_at.date()
    student_results = []
    for student in students:
        if student["account_status"] != "active":
            student_results.append(
                {
                    "user_id": student["user_id"],
                    "full_name": student["full_name"],
                    "email": student["email"],
                    "account_status": student["account_status"],
                    "total_hours": 0,
                    "daily_hours": [],
                }
            )
            continue
        seconds_by_day = daily_seconds[student["user_id"]]
        daily_hours = [
            {
                "date": (month_start + timedelta(days=index)).date().isoformat(),
                "day": index + 1,
                "hours": (
                    round(seconds / 3600, 2)
                    if (month_start + timedelta(days=index)).date() >= tracking_start_date
                    else None
                ),
            }
            for index, seconds in enumerate(seconds_by_day)
        ]
        student_results.append(
            {
                "user_id": student["user_id"],
                "full_name": student["full_name"],
                "email": student["email"],
                "account_status": student["account_status"],
                "total_hours": round(sum(seconds_by_day) / 3600, 2),
                "daily_hours": daily_hours,
            }
        )

    response = jsonify(
        {
            "month": month_value,
            "tracking_started_at": tracking_started_at.isoformat(),
            "students": student_results,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/admin/students")
def admin_create_student():
    if "user_id" not in session or session.get("role") != "admin":
        return json_error("Administrator access is required.", 403)
    if not request.is_json:
        return json_error("Send student account details as JSON.", 400)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return json_error("Send student account details as JSON.", 400)

    full_name = str(payload.get("full_name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    if not full_name or len(full_name) > 100:
        return json_error("Enter the student's full name (100 characters or fewer).", 400)
    if len(email) > 100 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return json_error("Enter a valid student email address.", 400)
    if len(password) < 8:
        return json_error("Use an initial password with at least 8 characters.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor()
            try:
                if not active_admin(cursor, session["user_id"]):
                    return json_error("Administrator access is no longer active.", 403)
                cursor.execute("SELECT role_id FROM roles WHERE role_key = %s", ("student",))
                student_role = cursor.fetchone()
                if not student_role:
                    app.logger.error("Student role is missing from python_app.roles")
                    return json_error("The student role is missing from python_app.roles.", 503)

                cursor.execute(
                    "INSERT INTO users (email, password_hash, full_name) VALUES (%s, %s, %s)",
                    (email, generate_password_hash(password), full_name),
                )
                student_user_id = cursor.lastrowid
                cursor.execute(
                    "INSERT IGNORE INTO user_roles (user_id, role_id) VALUES (%s, %s)",
                    (student_user_id, student_role[0]),
                )
                cursor.execute("INSERT INTO profiles (user_id) VALUES (%s)", (student_user_id,))
                record_admin_audit(
                    cursor,
                    session["user_id"],
                    "student.created",
                    "user",
                    student_user_id,
                    f"Student account created for {email}.",
                )
                connection.commit()
            except mysql.connector.IntegrityError:
                connection.rollback()
                return json_error("An account with that email already exists.", 409)
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while creating a student account")
        return json_error("Could not create the student account in python_app.", 503)

    return jsonify({"user_id": student_user_id, "message": "Student account created."}), 201


@app.patch("/api/admin/students/<int:student_id>")
def admin_update_student_status(student_id):
    if "user_id" not in session or session.get("role") != "admin":
        return json_error("Administrator access is required.", 403)
    if not request.is_json:
        return json_error("Send the account status as JSON.", 400)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("account_status") not in {"active", "suspended"}:
        return json_error("Choose active to reactivate or suspended to deactivate this student account.", 400)
    account_status = payload["account_status"]
    if account_status == "suspended" and student_id == session["user_id"]:
        return json_error("You cannot deactivate your own account.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if not active_admin(cursor, session["user_id"]):
                    return json_error("Administrator access is no longer active.", 403)
                cursor.execute(
                    "SELECT account_status FROM users WHERE user_id = %s FOR UPDATE",
                    (student_id,),
                )
                student = cursor.fetchone()
                if not student:
                    return json_error("This student account is unavailable.", 404)
                expected_status = "active" if account_status == "suspended" else "suspended"
                if student["account_status"] != expected_status:
                    return json_error(
                        "This student account is already active."
                        if account_status == "active"
                        else "This student account is already inactive.",
                        409,
                    )
                cursor.execute(
                    "SELECT MAX(r.role_key = 'student') AS has_student_role, "
                    "MAX(r.role_key = 'admin') AS has_admin_role "
                    "FROM user_roles AS ur "
                    "JOIN roles AS r ON r.role_id = ur.role_id "
                    "WHERE ur.user_id = %s",
                    (student_id,),
                )
                student_roles = cursor.fetchone()
                if not student_roles or not student_roles["has_student_role"] or student_roles["has_admin_role"]:
                    return json_error("This student account is unavailable.", 404)
                cursor.execute(
                    "UPDATE users SET account_status = %s "
                    "WHERE user_id = %s AND account_status = %s",
                    (account_status, student_id, expected_status),
                )
                reactivated = account_status == "active"
                record_admin_audit(
                    cursor,
                    session["user_id"],
                    "student.reactivated" if reactivated else "student.deactivated",
                    "user",
                    student_id,
                    (
                        "Student account reactivated; retained account data restored."
                        if reactivated
                        else "Student account deactivated; account data retained."
                    ),
                )
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while updating a student account status")
        return json_error("Could not update the student account in python_app.", 503)

    return jsonify({"user_id": student_id, "account_status": account_status})


@app.get("/api/admin/dashboard")
def admin_dashboard_data():
    if "user_id" not in session or session.get("role") != "admin":
        return json_error("Administrator access is required.", 403)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT u.full_name FROM users AS u "
                    "JOIN user_roles AS ur ON ur.user_id = u.user_id "
                    "JOIN roles AS r ON r.role_id = ur.role_id "
                    "WHERE u.user_id = %s AND u.account_status = 'active' "
                    "AND r.role_key = 'admin' LIMIT 1",
                    (session["user_id"],),
                )
                admin_user = cursor.fetchone()
                if not admin_user:
                    return json_error("Administrator access is no longer active.", 403)

                cursor.execute(
                    "SELECT "
                    "(SELECT COUNT(DISTINCT ur.user_id) FROM user_roles AS ur "
                    "JOIN roles AS r ON r.role_id = ur.role_id "
                    "JOIN users AS u ON u.user_id = ur.user_id "
                    "WHERE r.role_key = 'student' AND u.account_status = 'active') "
                    "AS student_count, "
                    "(SELECT COUNT(*) FROM resources) AS resource_count, "
                    "(SELECT COUNT(*) FROM resources WHERE status = 'pending') "
                    "AS pending_resource_count"
                )
                stats = cursor.fetchone()
                stats["course_count"] = len(RESOURCE_CATEGORIES)

                cursor.execute(
                    "SELECT r.resource_id, r.title, r.resource_type, r.status, "
                    "r.resource_category, r.description, r.file_url, "
                    "u.full_name AS uploader_name, c.name AS course_name "
                    "FROM resources AS r "
                    "JOIN users AS u ON u.user_id = r.uploaded_by "
                    "LEFT JOIN courses AS c ON c.course_id = r.course_id "
                    "WHERE r.status = 'pending' "
                    "ORDER BY r.created_at DESC, r.resource_id DESC"
                )
                pending_resources = cursor.fetchall()
                for resource in pending_resources:
                    resource["review_file_url"] = (
                        f"/api/admin/resources/{resource['resource_id']}/file"
                        if is_stored_resource_file(resource.get("file_url"))
                        else None
                    )

                cursor.execute(
                    "SELECT activity_type, heading, detail, occurred_at FROM ("
                    "SELECT 'new-user' AS activity_type, "
                    "'New student registered' AS heading, u.full_name AS detail, "
                    "u.created_at AS occurred_at "
                    "FROM users AS u "
                    "JOIN user_roles AS ur ON ur.user_id = u.user_id "
                    "JOIN roles AS r ON r.role_id = ur.role_id "
                    "WHERE r.role_key = 'student' "
                    "UNION ALL "
                    "SELECT 'new-resource', 'Resource submitted', "
                    "CONCAT(res.title, ' · ', u.full_name), res.created_at "
                    "FROM resources AS res "
                    "JOIN users AS u ON u.user_id = res.uploaded_by "
                    "UNION ALL "
                    "SELECT 'course-update', 'Course added', c.name, c.created_at "
                    "FROM courses AS c "
                    "UNION ALL "
                    "SELECT 'community-created', 'Community created', c.name, c.created_at "
                    "FROM communities AS c"
                    ") AS activity "
                    "ORDER BY occurred_at DESC LIMIT 8"
                )
                activity = cursor.fetchall()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading the admin dashboard")
        return json_error("Could not load admin dashboard data from python_app.", 503)

    return jsonify(
        {
            "admin_name": admin_user["full_name"],
            "stats": stats,
            "pending_resources": pending_resources,
            "activity": activity,
        }
    )


@app.get("/AcadexHomepage.html")
def home_page():
    return send_from_directory(BASE_DIR, "AcadexHomepage.html")


@app.get("/css/<path:filename>")
def css_asset(filename):
    return send_from_directory(BASE_DIR / "css", filename)


@app.get("/js/<path:filename>")
def javascript_asset(filename):
    return send_from_directory(BASE_DIR / "js", filename)


@app.get("/Acadex-logo.png")
def logo_asset():
    return send_from_directory(BASE_DIR, "Acadex-logo.png")


@app.post("/api/signup")
def signup():
    payload = request.get_json(silent=True) or {}
    full_name = str(payload.get("full_name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))

    if not full_name or len(full_name) > 100:
        return json_error("Enter your full name (100 characters or fewer).", 400)
    if len(email) > 100 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return json_error("Enter a valid email address.", 400)
    if len(password) < 8:
        return json_error("Use a password with at least 8 characters.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT role_id FROM roles WHERE role_key = %s", ("student",))
                student_role = cursor.fetchone()
                if not student_role:
                    return json_error("The student role is missing from python_app.roles.", 503)

                cursor.execute(
                    "INSERT INTO users (email, password_hash, full_name) VALUES (%s, %s, %s)",
                    (email, generate_password_hash(password), full_name),
                )
                user_id = cursor.lastrowid
                cursor.execute(
                    "INSERT IGNORE INTO user_roles (user_id, role_id) VALUES (%s, %s)",
                    (user_id, student_role[0]),
                )
                cursor.execute("INSERT INTO profiles (user_id) VALUES (%s)", (user_id,))
                connection.commit()
            except mysql.connector.IntegrityError:
                connection.rollback()
                return json_error("An account with that email already exists.", 409)
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while creating an account")
        return json_error("Could not reach the python_app database. Check the XAMPP MySQL settings.", 503)

    return jsonify({"message": "Account created. You can now log in."}), 201


@app.post("/api/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    wants_admin = bool(payload.get("admin", False))
    student_activity_id = None
    if not email or not password:
        return json_error("Enter your email and password.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT u.user_id, u.email, u.full_name, u.password_hash, u.account_status, "
                    "GROUP_CONCAT(r.role_key) AS role_keys "
                    "FROM users AS u "
                    "LEFT JOIN user_roles AS ur ON ur.user_id = u.user_id "
                    "LEFT JOIN roles AS r ON r.role_id = ur.role_id "
                    "WHERE u.email = %s GROUP BY u.user_id LIMIT 1",
                    (email,),
                )
                user = cursor.fetchone()
                if (
                    not user
                    or user["account_status"] != "active"
                    or not check_password_hash(user["password_hash"], password)
                ):
                    return json_error("Email or password is incorrect.", 401)

                role_keys = set((user["role_keys"] or "").split(","))
                requested_role = "admin" if wants_admin else "student"
                if requested_role not in role_keys:
                    if wants_admin:
                        return json_error("This account does not have administrator access.", 403)
                    return json_error("This account does not have student access.", 403)

                close_student_activity(
                    cursor,
                    session.get("student_activity_id"),
                    session.get("user_id"),
                )
                cursor.execute(
                    "UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE user_id = %s",
                    (user["user_id"],),
                )
                if requested_role == "student":
                    cursor.execute(
                        "INSERT INTO student_login_sessions (user_id) VALUES (%s)",
                        (user["user_id"],),
                    )
                    student_activity_id = cursor.lastrowid
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while signing in")
        return json_error("Could not reach the python_app database. Check the XAMPP MySQL settings.", 503)

    session.clear()
    session.permanent = True
    session["user_id"] = user["user_id"]
    session["full_name"] = user["full_name"]
    session["email"] = user["email"]
    session["role"] = requested_role
    if student_activity_id:
        session["student_activity_id"] = student_activity_id
    return jsonify({"message": "Signed in.", "role": requested_role})


@app.post("/api/forgot-password")
def forgot_password():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    if not email or len(email) > 100:
        return json_error("Enter the email address for your account.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT user_id, email FROM users "
                    "WHERE email = %s AND account_status = 'active' LIMIT 1",
                    (email,),
                )
                user = cursor.fetchone()
                if user:
                    cursor.execute(
                        "SELECT reset_id FROM password_reset_tokens "
                        "WHERE user_id = %s AND used_at IS NULL "
                        "AND created_at > CURRENT_TIMESTAMP - INTERVAL 60 SECOND "
                        "ORDER BY created_at DESC LIMIT 1",
                        (user["user_id"],),
                    )
                    if cursor.fetchone():
                        return json_error("Wait a minute before requesting another code.", 429)

                    otp = f"{secrets.randbelow(1_000_000):06d}"
                    cursor.execute(
                        "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP "
                        "WHERE user_id = %s AND used_at IS NULL",
                        (user["user_id"],),
                    )
                    cursor.execute(
                        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
                        "VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL 10 MINUTE)",
                        (user["user_id"], hash_otp(otp)),
                    )
                    connection.commit()
                    try:
                        send_otp_email(user["email"], otp)
                    except RuntimeError as error:
                        cursor.execute(
                            "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP "
                            "WHERE user_id = %s AND used_at IS NULL",
                            (user["user_id"],),
                        )
                        connection.commit()
                        app.logger.error("Password-reset email is not configured: %s", error)
                        return json_error(str(error), 503)
                    except TimeoutError:
                        cursor.execute(
                            "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP "
                            "WHERE user_id = %s AND used_at IS NULL",
                            (user["user_id"],),
                        )
                        connection.commit()
                        app.logger.exception("Timed out connecting to the password-reset SMTP server")
                        return json_error(
                            "Could not connect to the email server before the connection timed out. "
                            "Check your network or firewall, or use an SMTP provider reachable from this computer.",
                            503,
                        )
                    except smtplib.SMTPAuthenticationError:
                        cursor.execute(
                            "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP "
                            "WHERE user_id = %s AND used_at IS NULL",
                            (user["user_id"],),
                        )
                        connection.commit()
                        app.logger.exception("Gmail rejected password-reset SMTP authentication")
                        return json_error(
                            "The email provider rejected SMTP login. Check SMTP_USER and use a current "
                            "Google app password in SMTP_PASSWORD, then restart Flask.",
                            503,
                        )
                    except smtplib.SMTPServerDisconnected:
                        cursor.execute(
                            "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP "
                            "WHERE user_id = %s AND used_at IS NULL",
                            (user["user_id"],),
                        )
                        connection.commit()
                        app.logger.exception("SMTP server disconnected during password-reset email delivery")
                        return json_error(
                            "The SMTP server closed the connection during login or delivery. Verify "
                            "SMTP_USER and the current app password; if both are correct, check whether "
                            "a VPN, antivirus, proxy, or network policy is interrupting SMTP.",
                            503,
                        )
                    except (OSError, smtplib.SMTPException, ValueError):
                        cursor.execute(
                            "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP "
                            "WHERE user_id = %s AND used_at IS NULL",
                            (user["user_id"],),
                        )
                        connection.commit()
                        app.logger.exception("Could not send password-reset email")
                        return json_error(
                            "Email delivery failed. Check SMTP_HOST, SMTP_PORT, TLS settings, and provider credentials.",
                            503,
                        )
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while requesting a password reset")
        return json_error("Could not reach the python_app database. Check the XAMPP MySQL settings.", 503)

    return jsonify({"message": "If the account exists, a six-digit code has been sent."}), 200


@app.post("/api/verify-reset-otp")
def verify_reset_otp():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    otp = str(payload.get("otp", "")).strip()
    if not email or len(otp) != 6 or not otp.isdigit():
        return json_error("Enter your account email and the six-digit code.", 400)

    expected_hash = hash_otp(otp)
    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT pr.reset_id, pr.user_id, pr.token_hash "
                    "FROM password_reset_tokens AS pr "
                    "JOIN users AS u ON u.user_id = pr.user_id "
                    "WHERE u.email = %s AND u.account_status = 'active' "
                    "AND pr.used_at IS NULL AND pr.failed_attempts < 5 "
                    "AND pr.expires_at > CURRENT_TIMESTAMP "
                    "ORDER BY pr.created_at DESC LIMIT 1 FOR UPDATE",
                    (email,),
                )
                reset_token = cursor.fetchone()
                if not reset_token or not hmac.compare_digest(reset_token["token_hash"], expected_hash):
                    if reset_token:
                        cursor.execute(
                            "UPDATE password_reset_tokens "
                            "SET failed_attempts = failed_attempts + 1 WHERE reset_id = %s",
                            (reset_token["reset_id"],),
                        )
                        connection.commit()
                    return json_error("That code is invalid or expired. Request a new one.", 400)

                cursor.execute(
                    "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP WHERE reset_id = %s",
                    (reset_token["reset_id"],),
                )
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while resetting a password")
        return json_error("Could not reach the python_app database. Check the XAMPP MySQL settings.", 503)

    session["password_reset_user_id"] = reset_token["user_id"]
    session["password_reset_email"] = email
    session["password_reset_expires"] = int(time.time()) + 300
    return jsonify({"message": "Email verified. Set your new password."}), 200


@app.post("/api/reset-password")
def reset_password():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    new_password = str(payload.get("password", ""))
    if len(new_password) < 8:
        return json_error("Use a password with at least 8 characters.", 400)
    if (
        not session.get("password_reset_user_id")
        or session.get("password_reset_email") != email
        or int(session.get("password_reset_expires", 0)) < int(time.time())
    ):
        session.pop("password_reset_user_id", None)
        session.pop("password_reset_email", None)
        session.pop("password_reset_expires", None)
        return json_error("Verify a current email code before resetting your password.", 403)

    user_id = session["password_reset_user_id"]
    try:
        with database_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "UPDATE users SET password_hash = %s WHERE user_id = %s AND email = %s",
                    (generate_password_hash(new_password), user_id, email),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    return json_error("The account could not be found. Request a new code.", 400)
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while setting a new password")
        return json_error("Could not reach the python_app database. Check the XAMPP MySQL settings.", 503)

    session.pop("password_reset_user_id", None)
    session.pop("password_reset_email", None)
    session.pop("password_reset_expires", None)
    return jsonify({"message": "Password changed. You can now log in."}), 200


@app.get("/api/me")
def current_user():
    if "user_id" not in session:
        return json_error("Not signed in.", 401)

    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    "SELECT u.user_id, u.email, u.full_name, u.account_status, "
                    "p.institution, p.course_of_study, p.year_of_study, p.bio "
                    "FROM users AS u LEFT JOIN profiles AS p ON p.user_id = u.user_id "
                    "WHERE u.user_id = %s LIMIT 1",
                    (session["user_id"],),
                )
                user = cursor.fetchone()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while loading the signed-in profile")
        return json_error("Could not load the signed-in profile from python_app.", 503)

    if not user or user["account_status"] != "active":
        session.clear()
        return json_error("This account is unavailable. Please sign in again.", 401)

    session["full_name"] = user["full_name"]
    session["email"] = user["email"]
    return jsonify({
        "user_id": user["user_id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": session["role"],
        "institution": user["institution"] or "",
        "course_of_study": user["course_of_study"] or "",
        "year_of_study": user["year_of_study"],
        "bio": user["bio"] or "",
    })


@app.put("/api/profile")
def update_profile():
    if "user_id" not in session:
        return json_error("Sign in before updating your profile.", 401)

    payload = request.get_json(silent=True) or {}
    full_name = str(payload.get("full_name", "")).strip()
    institution = str(payload.get("institution", "")).strip()
    course = str(payload.get("course_of_study", "")).strip()
    bio = str(payload.get("bio", "")).strip()
    year_value = payload.get("year_of_study")

    if not full_name or len(full_name) > 100:
        return json_error("Enter your full name (100 characters or fewer).", 400)
    if len(institution) > 180 or len(course) > 180 or len(bio) > 400:
        return json_error("Profile details exceed their allowed length.", 400)
    if year_value in (None, ""):
        year_of_study = None
    else:
        try:
            year_of_study = int(year_value)
        except (TypeError, ValueError):
            return json_error("Choose a valid year of study.", 400)
        if not 1 <= year_of_study <= 6:
            return json_error("Choose a valid year of study.", 400)

    try:
        with database_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT user_id FROM users WHERE user_id = %s AND account_status = 'active' LIMIT 1",
                    (session["user_id"],),
                )
                if not cursor.fetchone():
                    return json_error("This account could not be updated. Please sign in again.", 401)
                cursor.execute(
                    "UPDATE users SET full_name = %s WHERE user_id = %s AND account_status = 'active'",
                    (full_name, session["user_id"]),
                )
                cursor.execute(
                    "INSERT INTO profiles (user_id, institution, course_of_study, year_of_study, bio) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE institution = VALUES(institution), "
                    "course_of_study = VALUES(course_of_study), "
                    "year_of_study = VALUES(year_of_study), bio = VALUES(bio)",
                    (session["user_id"], institution or None, course or None, year_of_study, bio or None),
                )
                connection.commit()
            finally:
                cursor.close()
    except mysql.connector.Error:
        app.logger.exception("MySQL error while updating the signed-in profile")
        return json_error("Could not save the profile to python_app.", 503)

    session["full_name"] = full_name
    return jsonify({"message": "Profile updated."})


@app.post("/api/logout")
def logout():
    if session.get("role") == "student" and session.get("student_activity_id"):
        try:
            with database_connection() as connection:
                cursor = connection.cursor()
                try:
                    close_student_activity(
                        cursor,
                        session["student_activity_id"],
                        session["user_id"],
                    )
                    connection.commit()
                finally:
                    cursor.close()
        except mysql.connector.Error:
            app.logger.exception("MySQL error while closing a student login session")
            return json_error("Could not save student session activity in python_app.", 503)
    session.clear()
    return jsonify({"message": "Signed out."})


if __name__ == "__main__":
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("Set SECRET_KEY in the local .env file before starting the server.")
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)

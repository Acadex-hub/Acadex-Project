import hashlib
import hmac
import os
import re
import secrets
import smtplib
import time
from contextlib import contextmanager
from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", ""),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
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


def hash_otp(otp):
    key = app.config["SECRET_KEY"].encode("utf-8")
    return hmac.new(key, otp.encode("ascii"), hashlib.sha256).hexdigest()


def send_otp_email(recipient, otp):
    host = os.environ.get("SMTP_HOST", "").strip()
    sender = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "")).strip()
    if not host or not sender:
        raise RuntimeError("SMTP email settings are missing.")

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
    return redirect("/indext.html?tab=login")


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


@app.get("/AdminPage.html")
def admin_dashboard():
    if "user_id" not in session:
        return redirect("/indext.html?tab=login")
    if session.get("role") != "admin":
        return redirect("/dashboard.html")
    return send_from_directory(BASE_DIR, "AdminPage.html")


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

                cursor.execute(
                    "UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE user_id = %s",
                    (user["user_id"],),
                )
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
                        "WHERE user_id = %s AND created_at > CURRENT_TIMESTAMP - INTERVAL 60 SECOND "
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
                    except (OSError, smtplib.SMTPException, RuntimeError):
                        cursor.execute(
                            "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP "
                            "WHERE user_id = %s AND used_at IS NULL",
                            (user["user_id"],),
                        )
                        connection.commit()
                        app.logger.exception("Could not send password-reset email")
                        return json_error("Email delivery is not configured or is unavailable.", 503)
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
    session.clear()
    return jsonify({"message": "Signed out."})


if __name__ == "__main__":
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("Set SECRET_KEY in the local .env file before starting the server.")
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)

# Acadex authentication with XAMPP MySQL

## Database

The application is configured for the existing `python_app` database. The current XAMPP database already contains the users, roles, user_roles, and password_reset_tokens tables. The app matches the observed schema and does not recreate the database.

The backend adds a five-attempt limit to reset-code verification. It has been applied to the current database; for a fresh import, `database/01_accounts.sql` includes the column and migration.

Run scripts `database/01_accounts.sql` through `database/04_admin.sql` in order only when setting up a fresh schema. These scripts point to `python_app`.

## Python setup

From this project folder:

```powershell
py -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`:

- Keep `DB_NAME=python_app`; set `DB_USER` and `DB_PASSWORD` to your XAMPP MySQL credentials.
- Replace `SECRET_KEY` with a random secret. Generate one with `py -c "import secrets; print(secrets.token_urlsafe(48))"`.
- Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM`. Use an SMTP app password where required. Do not commit `.env`.

For a local XAMPP account using `root` with no password, `DB_USER=root` and an empty `DB_PASSWORD` work by default. Keep that setup local only.

## Start the site

```powershell
py app.py
```

Open `http://127.0.0.1:5000/indext.html?tab=login`. Do not open `indext.html` as a `file://` URL; the browser needs to use the Flask origin to call the API and receive the login session cookie.

Signup creates a student account with a Werkzeug password hash. Login checks the database and the selected student/admin role. New public signups cannot grant themselves admin access.

After sign-in, the student dashboard loads the account name, email, institution, course, study year, and bio from `/api/me`. Profile edits save the account name and academic details to `users` and `profiles`. The profile photo is cached in browser storage under that account's user ID; it is not uploaded to MySQL or shared across devices.

To grant an existing account admin access in phpMyAdmin, run this after replacing the email:

```sql
INSERT IGNORE INTO roles (role_id, role_key, display_name)
SELECT COALESCE(MAX(role_id), 0) + 1, 'admin', 'Administrator'
FROM roles;

INSERT IGNORE INTO user_roles (user_id, role_id)
SELECT u.user_id, r.role_id
FROM users AS u
JOIN roles AS r ON r.role_key = 'admin'
WHERE u.email = 'admin@example.com';
```

Forgot password sends a cryptographically random six-digit OTP, stores only its keyed hash, expires it after 10 minutes, throttles resend requests, limits guesses to five, and allows it to be used once. The user must verify the code first; only then does the page reveal the new-password form. Verification grants a five-minute, signed-session reset permission. Email recovery requires valid SMTP configuration.

The MySQL integration test is run with:

```powershell
py -m unittest discover -s tests -v
```

It uses a unique temporary account, mocks only SMTP delivery, and removes the test account after completion.

The Flask development server is for local development, not production. Enable HTTPS and set `SESSION_COOKIE_SECURE=true` when deploying behind HTTPS.

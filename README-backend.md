# Acadex authentication with XAMPP MySQL

## Database

The application is configured for the existing `python_app` database. The current XAMPP database already contains the users, roles, user_roles, and password_reset_tokens tables. The app matches the observed schema and does not recreate the database.

See [database/DATABASE_DESIGN.md](database/DATABASE_DESIGN.md) for the entity-relationship diagram, table definitions, constraints, storage boundaries, and current API coverage.

See [System_Design_Phase.md](System_Design_Phase.md) for the project system-design report, including software, hardware, network, database, program, interface, and security/backup designs.

The backend adds a five-attempt limit to reset-code verification. It has been applied to the current database; for a fresh import, `database/01_accounts.sql` includes the column and migration.

Run scripts `database/01_accounts.sql` through `database/04_admin.sql` in order only when setting up a fresh schema. Then run `database/05_it_communities.sql` through `database/13_community_chat.sql` in order on both fresh and existing databases to add community fields/topics, resource categories, persistent direct messages, end-to-end encryption, private-message file storage, BA Communities, student login activity tracking, the Business Administration resource-folder label, and persistent community chat. Migration 13 imports existing community posts as announcements and is safe to rerun. Migration 08 deletes existing plaintext private messages because they cannot be converted into encrypted messages.

## Python setup

From this project folder:

```powershell
py -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`:

- Keep `DB_NAME=python_app`; set `DB_USER` and `DB_PASSWORD` to your XAMPP MySQL credentials.
- Replace `SECRET_KEY` with a random secret. Generate one with `py -c "import secrets; print(secrets.token_urlsafe(48))"`.
- Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM` for an SMTP account you control. The example uses Gmail; use a Gmail app password rather than your account password. Other providers may require different host, port, and TLS settings. Do not commit `.env`.

For a local XAMPP account using `root` with no password, `DB_USER=root` and an empty `DB_PASSWORD` work by default. Keep that setup local only.

## Start the site

```powershell
py app.py
```

Open `http://127.0.0.1:5000/` to start at the Acadex homepage. Use its Log In or Get Started links to access `indext.html` through Flask; do not open `indext.html` as a `file://` URL, because the browser needs to use the Flask origin to call the API and receive the login session cookie. Password reset requires valid SMTP settings in `.env`; a missing configuration is reported in the reset form.

Signup creates a student account with a Werkzeug password hash. Login checks the database and the selected student/admin role. New public signups cannot grant themselves admin access.

After sign-in, the student dashboard loads the account name, email, institution, course, study year, and bio from `/api/me`. Profile edits save the account name and academic details to `users` and `profiles`. The profile photo is cached in browser storage under that account's user ID; it is not uploaded to MySQL or shared across devices.

Students can join the seeded IT Communities and BA Communities or create a public community in a topic within either group. The creator is automatically added as the community owner. Joined communities have persistent group chats; members can send chat messages or announcements, pin/unpin their own messages, and highlight/remove the highlight from their own messages. Community owners and moderators can manage any message in their community.

Students can submit PDF, DOC, or DOCX resources (up to 10 MB) to the Information Technology (IT) or Business Administration (BA) library folder as Notes, Articles, or Past Papers & Memos. Uploads are stored in the ignored `uploads/resources/` directory and remain unavailable to students until an administrator approves them. Administrators can download, approve, or reject pending resources from the dashboard.

The homepage and login page show live counts of approved resources and notes (and the homepage also shows approved past papers and active courses). These public totals update immediately across open pages in the same browser after approval, refresh every five seconds for other clients, and refresh when a page becomes visible. Pending and rejected uploads are not counted.

Students can invite active student accounts from Discover, accept or decline incoming requests, and message accepted friends. The browser encrypts each message with AES-GCM, wraps its key separately to each participant with RSA-OAEP, and signs the encrypted payload with the sender's ECDSA identity key. Files up to 10 MB are encrypted in the browser before upload; the server stores opaque ciphertext in the ignored `uploads/private_messages/` directory, and the encrypted message contains the file name, key envelopes, and integrity digest. Only participants in the accepted friendship can download an attachment linked to a sent message. Encryption and signing private keys stay in the browser's IndexedDB; they cannot be recovered on a different browser or after clearing that browser's data. Users must compare and explicitly verify each friend's displayed fingerprint through a separate trusted channel before opening or sending messages. Verified public-key changes are pinned and stop messaging. This uses trust-on-first-use and does not provide forward secrecy. Deploy the site over HTTPS outside localhost.

The admin dashboard reads active student, resource, course-folder, and pending-review totals from MySQL. Its Courses panel has IT and Business Administration (BA) folders showing all currently approved materials. Administrators can add PDF, DOC, or DOCX materials directly to the student library or archive existing materials; archived files and records are retained, and archived materials are hidden from students. These publishing and archive actions are recorded in the audit log. Its moderation queue and recent activity refresh every minute while the dashboard is open. The dashboard's Audit log shows the latest 50 administrator actions; active admins can also request 1–100 entries from `GET /api/admin/audit-logs?limit=50`. The displayed date and footer year use the browser's current local date.

Run `database/11_student_login_activity.sql` on an existing database before using the student activity report. Select **Student Accounts** under Platform Tools (or **Students** in the sidebar) to see active and suspended student accounts, active students' selected-month login totals, and a daily hours bar chart. Administrators can add a student account there, deactivate an active student, or reactivate a suspended student. Reactivation restores sign-in with the existing password and retained account data; account creation, deactivation, and reactivation are recorded in the audit log. Login time is recorded while the student dashboard sends a heartbeat each minute; sessions expire from reporting after two minutes without a heartbeat and close at logout. The report splits session time at midnight and merges overlapping sessions. Tracking starts when migration 11 is applied; earlier days are marked as having no data and cannot be backfilled.

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

The Python and browser-crypto tests are run with:

```powershell
py -m unittest discover -s tests -v
node --test tests\secure_messaging_crypto.test.js
```

It uses a unique temporary account, mocks only SMTP delivery, and removes the test account after completion.

The Flask development server is for local development, not production. Enable HTTPS and set `SESSION_COOKIE_SECURE=true` when deploying behind HTTPS.

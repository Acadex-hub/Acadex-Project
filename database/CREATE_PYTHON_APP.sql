-- Acadex fresh-schema import for MySQL Workbench.
-- Run this complete script only for a fresh python_app database.
-- Migration 08 removes legacy plaintext private messages on existing installs.

-- ===== 01_accounts.sql =====
CREATE DATABASE IF NOT EXISTS python_app
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE python_app;

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    email VARCHAR(254) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(150) NOT NULL,
    student_number VARCHAR(64) NULL,
    account_status ENUM('active', 'pending', 'suspended', 'deleted') NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP NULL DEFAULT NULL,
    PRIMARY KEY (user_id),
    UNIQUE KEY uq_users_email (email),
    UNIQUE KEY uq_users_student_number (student_number)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS roles (
    role_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    role_key VARCHAR(32) NOT NULL,
    display_name VARCHAR(64) NOT NULL,
    PRIMARY KEY (role_id),
    UNIQUE KEY uq_roles_key (role_key)
) ENGINE=InnoDB;

INSERT IGNORE INTO roles (role_key, display_name)
VALUES ('student', 'Student'), ('admin', 'Administrator');

CREATE TABLE IF NOT EXISTS user_roles (
    user_id BIGINT UNSIGNED NOT NULL,
    role_id SMALLINT UNSIGNED NOT NULL,
    assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id)
        REFERENCES roles (role_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

DROP TRIGGER IF EXISTS assign_student_role_to_new_user;
CREATE TRIGGER assign_student_role_to_new_user
AFTER INSERT ON users FOR EACH ROW
INSERT INTO user_roles (user_id, role_id)
SELECT NEW.user_id, role_id
FROM roles
WHERE role_key = 'student';

CREATE TABLE IF NOT EXISTS user_sessions (
    session_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    token_hash CHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    revoked_at DATETIME NULL DEFAULT NULL,
    PRIMARY KEY (session_id),
    UNIQUE KEY uq_user_sessions_token_hash (token_hash),
    KEY idx_user_sessions_user_expiry (user_id, expires_at),
    CONSTRAINT fk_user_sessions_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    reset_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    token_hash CHAR(64) NOT NULL,
    failed_attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    used_at DATETIME NULL DEFAULT NULL,
    PRIMARY KEY (reset_id),
    UNIQUE KEY uq_password_reset_token_hash (token_hash),
    KEY idx_password_reset_user_expiry (user_id, expires_at),
    CONSTRAINT fk_password_reset_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

SET @reset_attempt_column_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'password_reset_tokens'
      AND COLUMN_NAME = 'failed_attempts'
);
SET @reset_attempt_migration = IF(
    @reset_attempt_column_exists = 0,
    'ALTER TABLE password_reset_tokens ADD COLUMN failed_attempts TINYINT UNSIGNED NOT NULL DEFAULT 0',
    'SELECT 1'
);
PREPARE reset_attempt_statement FROM @reset_attempt_migration;
EXECUTE reset_attempt_statement;
DEALLOCATE PREPARE reset_attempt_statement;

-- ===== 02_academic.sql =====
USE python_app;

CREATE TABLE IF NOT EXISTS profiles (
    user_id BIGINT UNSIGNED NOT NULL,
    institution VARCHAR(180) NULL,
    course_of_study VARCHAR(180) NULL,
    year_of_study SMALLINT UNSIGNED NULL,
    bio TEXT NULL,
    avatar_url VARCHAR(2048) NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id),
    CONSTRAINT fk_profiles_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS courses (
    course_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_code VARCHAR(64) NULL,
    name VARCHAR(180) NOT NULL,
    description TEXT NULL,
    institution VARCHAR(180) NULL,
    is_active TINYINT(1) UNSIGNED NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (course_id),
    UNIQUE KEY uq_courses_code (course_code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_courses (
    user_id BIGINT UNSIGNED NOT NULL,
    course_id BIGINT UNSIGNED NOT NULL,
    enrollment_status ENUM('current', 'completed', 'withdrawn') NOT NULL DEFAULT 'current',
    progress_percent DECIMAL(5,2) NOT NULL DEFAULT 0,
    enrolled_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, course_id),
    CONSTRAINT chk_user_courses_progress CHECK (progress_percent BETWEEN 0 AND 100),
    CONSTRAINT fk_user_courses_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_user_courses_course FOREIGN KEY (course_id)
        REFERENCES courses (course_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS resources (
    resource_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_id BIGINT UNSIGNED NULL,
    uploaded_by BIGINT UNSIGNED NOT NULL,
    reviewed_by BIGINT UNSIGNED NULL,
    title VARCHAR(220) NOT NULL,
    description TEXT NULL,
    resource_type ENUM('article', 'notes', 'past_paper', 'study_guide', 'other') NOT NULL,
    resource_category VARCHAR(32) NOT NULL DEFAULT 'IT',
    file_url VARCHAR(2048) NULL,
    source_url VARCHAR(2048) NULL,
    status ENUM('pending', 'approved', 'rejected', 'archived') NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP NULL DEFAULT NULL,
    PRIMARY KEY (resource_id),
    KEY idx_resources_status_created (status, created_at),
    KEY idx_resources_course_type (course_id, resource_type),
    CONSTRAINT fk_resources_course FOREIGN KEY (course_id)
        REFERENCES courses (course_id) ON DELETE SET NULL,
    CONSTRAINT fk_resources_uploader FOREIGN KEY (uploaded_by)
        REFERENCES users (user_id) ON DELETE RESTRICT,
    CONSTRAINT fk_resources_reviewer FOREIGN KEY (reviewed_by)
        REFERENCES users (user_id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS saved_resources (
    user_id BIGINT UNSIGNED NOT NULL,
    resource_id BIGINT UNSIGNED NOT NULL,
    saved_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, resource_id),
    CONSTRAINT fk_saved_resources_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_saved_resources_resource FOREIGN KEY (resource_id)
        REFERENCES resources (resource_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS resource_progress (
    user_id BIGINT UNSIGNED NOT NULL,
    resource_id BIGINT UNSIGNED NOT NULL,
    progress_percent DECIMAL(5,2) NOT NULL DEFAULT 0,
    status ENUM('in_progress', 'completed') NOT NULL DEFAULT 'in_progress',
    last_accessed_at TIMESTAMP NULL DEFAULT NULL,
    completed_at TIMESTAMP NULL DEFAULT NULL,
    PRIMARY KEY (user_id, resource_id),
    CONSTRAINT chk_resource_progress_percent CHECK (progress_percent BETWEEN 0 AND 100),
    CONSTRAINT fk_resource_progress_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_resource_progress_resource FOREIGN KEY (resource_id)
        REFERENCES resources (resource_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS assignments (
    assignment_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    course_id BIGINT UNSIGNED NULL,
    title VARCHAR(220) NOT NULL,
    description TEXT NULL,
    due_at DATETIME NULL,
    status ENUM('upcoming', 'in_progress', 'completed', 'cancelled') NOT NULL DEFAULT 'upcoming',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (assignment_id),
    KEY idx_assignments_user_due (user_id, due_at),
    CONSTRAINT fk_assignments_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_assignments_course FOREIGN KEY (course_id)
        REFERENCES courses (course_id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ===== 03_social.sql =====
USE python_app;

CREATE TABLE IF NOT EXISTS friendships (
    user_id_a BIGINT UNSIGNED NOT NULL,
    user_id_b BIGINT UNSIGNED NOT NULL,
    requested_by BIGINT UNSIGNED NOT NULL,
    status ENUM('pending', 'accepted', 'rejected', 'blocked') NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id_a, user_id_b),
    KEY idx_friendships_b_status (user_id_b, status),
    CONSTRAINT chk_friendship_pair CHECK (user_id_a < user_id_b),
    CONSTRAINT chk_friendship_requester CHECK (requested_by = user_id_a OR requested_by = user_id_b),
    CONSTRAINT fk_friendships_user_a FOREIGN KEY (user_id_a)
        REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_friendships_user_b FOREIGN KEY (user_id_b)
        REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_friendships_requester FOREIGN KEY (requested_by)
        REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS communities (
    community_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_id BIGINT UNSIGNED NULL,
    created_by BIGINT UNSIGNED NULL,
    name VARCHAR(180) NOT NULL,
    description TEXT NULL,
    community_group VARCHAR(100) NOT NULL DEFAULT 'IT Communities',
    community_category VARCHAR(100) NOT NULL DEFAULT 'IT Communities',
    community_key VARCHAR(64) NULL,
    visibility ENUM('public', 'private') NOT NULL DEFAULT 'public',
    status ENUM('active', 'archived') NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (community_id),
    KEY idx_communities_course_status (course_id, status),
    UNIQUE KEY uq_communities_key (community_key),
    CONSTRAINT fk_communities_course FOREIGN KEY (course_id)
        REFERENCES courses (course_id) ON DELETE SET NULL,
    CONSTRAINT fk_communities_creator FOREIGN KEY (created_by)
        REFERENCES users (user_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS community_members (
    community_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    member_role ENUM('owner', 'moderator', 'member') NOT NULL DEFAULT 'member',
    status ENUM('invited', 'active', 'left', 'banned') NOT NULL DEFAULT 'active',
    joined_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (community_id, user_id),
    KEY idx_community_members_user_status (user_id, status),
    CONSTRAINT fk_community_members_community FOREIGN KEY (community_id)
        REFERENCES communities (community_id) ON DELETE CASCADE,
    CONSTRAINT fk_community_members_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS community_posts (
    post_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    community_id BIGINT UNSIGNED NOT NULL,
    author_id BIGINT UNSIGNED NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (post_id),
    KEY idx_community_posts_created (community_id, created_at),
    CONSTRAINT fk_community_posts_community FOREIGN KEY (community_id)
        REFERENCES communities (community_id) ON DELETE CASCADE,
    CONSTRAINT fk_community_posts_author FOREIGN KEY (author_id)
        REFERENCES users (user_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- ===== 04_admin.sql =====
USE python_app;

CREATE TABLE IF NOT EXISTS admin_audit_log (
    audit_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    admin_user_id BIGINT UNSIGNED NOT NULL,
    action VARCHAR(100) NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_id BIGINT UNSIGNED NULL,
    details TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (audit_id),
    KEY idx_admin_audit_admin_created (admin_user_id, created_at),
    KEY idx_admin_audit_target (target_type, target_id),
    CONSTRAINT fk_admin_audit_admin FOREIGN KEY (admin_user_id)
        REFERENCES users (user_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- ===== 05_it_communities.sql =====
USE python_app;

SET @community_category_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'communities'
      AND COLUMN_NAME = 'community_category'
);
SET @community_category_migration = IF(
    @community_category_exists = 0,
    'ALTER TABLE communities ADD COLUMN community_category VARCHAR(100) NOT NULL DEFAULT ''IT Communities'' AFTER description',
    'SELECT 1'
);
PREPARE community_category_statement FROM @community_category_migration;
EXECUTE community_category_statement;
DEALLOCATE PREPARE community_category_statement;

SET @community_key_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'communities'
      AND COLUMN_NAME = 'community_key'
);
SET @community_key_migration = IF(
    @community_key_exists = 0,
    'ALTER TABLE communities ADD COLUMN community_key VARCHAR(64) NULL',
    'SELECT 1'
);
PREPARE community_key_statement FROM @community_key_migration;
EXECUTE community_key_statement;
DEALLOCATE PREPARE community_key_statement;

SET @community_key_index_exists = (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'communities'
      AND INDEX_NAME = 'uq_communities_key'
);
SET @community_key_index_migration = IF(
    @community_key_index_exists = 0,
    'ALTER TABLE communities ADD UNIQUE KEY uq_communities_key (community_key)',
    'SELECT 1'
);
PREPARE community_key_index_statement FROM @community_key_index_migration;
EXECUTE community_key_index_statement;
DEALLOCATE PREPARE community_key_index_statement;

SET @community_creator_column_type = (
    SELECT COLUMN_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'communities'
      AND COLUMN_NAME = 'created_by'
    LIMIT 1
);
SET @community_user_id_type = (
    SELECT COLUMN_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'user_id'
    LIMIT 1
);
SET @community_creator_is_nullable = (
    SELECT IS_NULLABLE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'communities'
      AND COLUMN_NAME = 'created_by'
    LIMIT 1
);
SET @community_creator_needs_update = (
    @community_creator_is_nullable = 'NO'
      OR @community_creator_column_type <> @community_user_id_type
);
SET @community_creator_foreign_key = (
    SELECT CONSTRAINT_NAME
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'communities'
      AND COLUMN_NAME = 'created_by'
      AND REFERENCED_TABLE_NAME = 'users'
    LIMIT 1
);
SET @community_creator_fk_drop = IF(
    @community_creator_needs_update
      AND @community_creator_foreign_key IS NOT NULL,
    CONCAT(
        'ALTER TABLE communities DROP FOREIGN KEY `',
        REPLACE(@community_creator_foreign_key, '`', '``'),
        '`'
    ),
    'SELECT 1'
);
PREPARE community_creator_fk_drop_statement FROM @community_creator_fk_drop;
EXECUTE community_creator_fk_drop_statement;
DEALLOCATE PREPARE community_creator_fk_drop_statement;

SET @community_creator_migration = IF(
    @community_creator_needs_update,
    CONCAT(
        'ALTER TABLE communities MODIFY created_by ',
        @community_user_id_type,
        ' NULL'
    ),
    'SELECT 1'
);
PREPARE community_creator_statement FROM @community_creator_migration;
EXECUTE community_creator_statement;
DEALLOCATE PREPARE community_creator_statement;

SET @community_creator_fk_exists = (
    SELECT COUNT(*)
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'communities'
      AND COLUMN_NAME = 'created_by'
      AND REFERENCED_TABLE_NAME = 'users'
);
SET @community_creator_fk_migration = IF(
    @community_creator_fk_exists = 0,
    'ALTER TABLE communities ADD CONSTRAINT fk_communities_creator FOREIGN KEY (created_by) REFERENCES users (user_id) ON DELETE RESTRICT',
    'SELECT 1'
);
PREPARE community_creator_fk_statement FROM @community_creator_fk_migration;
EXECUTE community_creator_fk_statement;
DEALLOCATE PREPARE community_creator_fk_statement;

UPDATE communities
SET community_key = IF(
        NOT EXISTS (
            SELECT 1
            FROM (
                SELECT community_key
                FROM communities
                WHERE community_key = 'it-programming-python'
            ) AS existing_python_community
        ),
        'it-programming-python',
        community_key
    ),
    name = 'Programming Python',
    description = 'Learn and collaborate on Python programming.',
    community_category = 'Programming Python'
WHERE community_key = 'it-programming-phython'
   OR name = 'Programming Phython'
   OR community_category = 'Programming Phython';

INSERT IGNORE INTO communities
    (community_key, course_id, created_by, name, description, community_category, visibility, status)
VALUES
    ('it-database', NULL, NULL, 'Database', 'Explore database design, SQL, and data management.', 'Database', 'public', 'active'),
    ('it-information-systems', NULL, NULL, 'Information Systems', 'Discuss information systems, analysis, and business technology.', 'Information Systems', 'public', 'active'),
    ('it-software-engineering', NULL, NULL, 'Software Engineering', 'Share software design, development, and testing practices.', 'Software Engineering', 'public', 'active'),
    ('it-programming-cpp', NULL, NULL, 'Programming C++', 'Learn and collaborate on C++ programming.', 'Programming C++', 'public', 'active'),
    ('it-programming-java', NULL, NULL, 'Programming JAVA', 'Learn and collaborate on Java programming.', 'Programming JAVA', 'public', 'active'),
    ('it-programming-python', NULL, NULL, 'Programming Python', 'Learn and collaborate on Python programming.', 'Programming Python', 'public', 'active'),
    ('it-data-science', NULL, NULL, 'Data Science', 'Explore data analysis, statistics, and practical data science.', 'Data Science', 'public', 'active'),
    ('it-robotics', NULL, NULL, 'Robotics', 'Discuss robotics, automation, and intelligent systems.', 'Robotics', 'public', 'active'),
    ('it-cybersecurity', NULL, NULL, 'CyberSecurity', 'Learn about cybersecurity and responsible digital defense.', 'CyberSecurity', 'public', 'active'),
    ('it-machine-learning', NULL, NULL, 'Machine Learning', 'Explore machine learning concepts, models, and applications.', 'Machine Learning', 'public', 'active'),
    ('it-mathematics', NULL, NULL, 'Mathematics', 'Work through mathematics topics and problem-solving together.', 'Mathematics', 'public', 'active'),
    ('it-cloud-computing', NULL, NULL, 'Cloud Computing', 'Discuss cloud platforms, architecture, and services.', 'Cloud Computing', 'public', 'active');

-- ===== 06_resource_uploads.sql =====
USE python_app;

SET @resource_category_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'resources'
      AND COLUMN_NAME = 'resource_category'
);
SET @resource_category_migration = IF(
    @resource_category_exists = 0,
    'ALTER TABLE resources ADD COLUMN resource_category VARCHAR(32) NOT NULL DEFAULT ''IT'' AFTER resource_type',
    'SELECT 1'
);
PREPARE resource_category_statement FROM @resource_category_migration;
EXECUTE resource_category_statement;
DEALLOCATE PREPARE resource_category_statement;

SET @resource_category_index_exists = (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'resources'
      AND INDEX_NAME = 'idx_resources_category_status'
);
SET @resource_category_index_migration = IF(
    @resource_category_index_exists = 0,
    'ALTER TABLE resources ADD KEY idx_resources_category_status (resource_category, status, created_at)',
    'SELECT 1'
);
PREPARE resource_category_index_statement FROM @resource_category_index_migration;
EXECUTE resource_category_index_statement;
DEALLOCATE PREPARE resource_category_index_statement;

SET @resource_category_backfill = IF(
    @resource_category_exists = 0,
    'UPDATE resources AS r JOIN courses AS c ON c.course_id = r.course_id SET r.resource_category = ''Business Studies'' WHERE LOWER(c.name) LIKE ''%business%''',
    'SELECT 1'
);
PREPARE resource_category_backfill_statement FROM @resource_category_backfill;
EXECUTE resource_category_backfill_statement;
DEALLOCATE PREPARE resource_category_backfill_statement;

-- ===== 07_private_messaging.sql =====
USE python_app;

SET @user_id_type = (
    SELECT COLUMN_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'user_id'
);

SET @private_messages_sql = CONCAT(
    'CREATE TABLE IF NOT EXISTS private_messages (',
    'message_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,',
    'sender_id ', @user_id_type, ' NOT NULL,',
    'recipient_id ', @user_id_type, ' NOT NULL,',
    'body VARCHAR(2000) NOT NULL,',
    'created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,',
    'PRIMARY KEY (message_id),',
    'KEY idx_private_messages_conversation (sender_id, recipient_id, message_id),',
    'KEY idx_private_messages_recipient (recipient_id, message_id),',
    'CONSTRAINT fk_private_messages_sender FOREIGN KEY (sender_id) ',
    'REFERENCES users (user_id) ON DELETE CASCADE,',
    'CONSTRAINT fk_private_messages_recipient FOREIGN KEY (recipient_id) ',
    'REFERENCES users (user_id) ON DELETE CASCADE',
    ') ENGINE=InnoDB'
);

PREPARE create_private_messages FROM @private_messages_sql;
EXECUTE create_private_messages;
DEALLOCATE PREPARE create_private_messages;

-- ===== 08_end_to_end_encryption.sql =====
USE python_app;

SET @user_id_type = (
    SELECT COLUMN_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'user_id'
);

SET @encryption_keys_sql = CONCAT(
    'CREATE TABLE IF NOT EXISTS user_encryption_keys (',
    'user_id ', @user_id_type, ' NOT NULL,',
    'public_key VARCHAR(2048) NOT NULL,',
    'created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,',
    'updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,',
    'PRIMARY KEY (user_id),',
    'CONSTRAINT fk_user_encryption_keys_user FOREIGN KEY (user_id) ',
    'REFERENCES users (user_id) ON DELETE CASCADE',
    ') ENGINE=InnoDB'
);

PREPARE create_user_encryption_keys FROM @encryption_keys_sql;
EXECUTE create_user_encryption_keys;
DEALLOCATE PREPARE create_user_encryption_keys;

SET @has_legacy_body = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'private_messages'
      AND COLUMN_NAME = 'body'
);

SET @has_encrypted_payload = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'private_messages'
      AND COLUMN_NAME = 'encrypted_payload'
);

SET @delete_legacy_messages_sql = IF(
    @has_legacy_body = 1 AND @has_encrypted_payload = 0,
    'DELETE FROM private_messages',
    'DO 0'
);
PREPARE delete_legacy_messages FROM @delete_legacy_messages_sql;
EXECUTE delete_legacy_messages;
DEALLOCATE PREPARE delete_legacy_messages;

SET @rename_message_body_sql = IF(
    @has_legacy_body = 1 AND @has_encrypted_payload = 0,
    'ALTER TABLE private_messages CHANGE COLUMN body encrypted_payload LONGTEXT NOT NULL',
    'DO 0'
);
PREPARE rename_message_body FROM @rename_message_body_sql;
EXECUTE rename_message_body;
DEALLOCATE PREPARE rename_message_body;

-- ===== 09_encrypted_attachments.sql =====
USE python_app;

SET @user_id_type = (
    SELECT COLUMN_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'user_id'
);

SET @private_message_attachments_sql = CONCAT(
    'CREATE TABLE IF NOT EXISTS private_message_attachments (',
    'attachment_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,',
    'sender_id ', @user_id_type, ' NOT NULL,',
    'recipient_id ', @user_id_type, ' NOT NULL,',
    'message_id BIGINT UNSIGNED NULL,',
    'storage_name CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,',
    'encrypted_size INT UNSIGNED NOT NULL,',
    'created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,',
    'PRIMARY KEY (attachment_id),',
    'UNIQUE KEY uq_private_message_attachment_storage (storage_name),',
    'KEY idx_private_message_attachments_message (message_id),',
    'CONSTRAINT fk_private_message_attachments_sender FOREIGN KEY (sender_id) ',
    'REFERENCES users (user_id) ON DELETE CASCADE,',
    'CONSTRAINT fk_private_message_attachments_recipient FOREIGN KEY (recipient_id) ',
    'REFERENCES users (user_id) ON DELETE CASCADE,',
    'CONSTRAINT fk_private_message_attachments_message FOREIGN KEY (message_id) ',
    'REFERENCES private_messages (message_id) ON DELETE CASCADE',
    ') ENGINE=InnoDB'
);

PREPARE create_private_message_attachments FROM @private_message_attachments_sql;
EXECUTE create_private_message_attachments;
DEALLOCATE PREPARE create_private_message_attachments;

-- ===== 10_ba_communities.sql =====
USE python_app;

SET @community_group_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'communities'
      AND COLUMN_NAME = 'community_group'
);
SET @community_group_migration = IF(
    @community_group_exists = 0,
    'ALTER TABLE communities ADD COLUMN community_group VARCHAR(100) NOT NULL DEFAULT ''IT Communities'' AFTER description',
    'SELECT 1'
);
PREPARE community_group_statement FROM @community_group_migration;
EXECUTE community_group_statement;
DEALLOCATE PREPARE community_group_statement;

INSERT IGNORE INTO communities
    (community_key, course_id, created_by, name, description, community_group,
     community_category, visibility, status)
VALUES
    ('ba-accounting', NULL, NULL, 'Accounting', 'Discuss accounting principles, financial reporting, and practical problem-solving.', 'BA Communities', 'Accounting', 'public', 'active'),
    ('ba-commercial-law', NULL, NULL, 'Commercial law', 'Explore commercial law concepts and their application in business.', 'BA Communities', 'Commercial law', 'public', 'active'),
    ('ba-business-management', NULL, NULL, 'Business Management', 'Share ideas on managing people, organizations, and business operations.', 'BA Communities', 'Business Management', 'public', 'active'),
    ('ba-supply-chain', NULL, NULL, 'Supply Chain', 'Discuss procurement, logistics, and supply-chain management.', 'BA Communities', 'Supply Chain', 'public', 'active'),
    ('ba-economics', NULL, NULL, 'Economics', 'Explore economic theory, policy, markets, and current issues.', 'BA Communities', 'Economics', 'public', 'active'),
    ('ba-information-systems', NULL, NULL, 'Information Systems', 'Discuss how information systems support business processes and decisions.', 'BA Communities', 'Information Systems', 'public', 'active'),
    ('ba-business-ethics', NULL, NULL, 'Business Ethics', 'Discuss ethical decision-making and responsibility in business.', 'BA Communities', 'Business Ethics', 'public', 'active'),
    ('ba-industrial-phsycology', NULL, NULL, 'Industrial Phsycology', 'Explore psychology in the workplace and organizational behavior.', 'BA Communities', 'Industrial Phsycology', 'public', 'active'),
    ('ba-statistics', NULL, NULL, 'Statistics', 'Study statistical methods and their application to business data.', 'BA Communities', 'Statistics', 'public', 'active');

-- ===== 11_student_login_activity.sql =====
USE python_app;

SET @student_activity_user_id_type = (
    SELECT COLUMN_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'user_id'
);
SET @student_login_sessions_migration = CONCAT(
    'CREATE TABLE IF NOT EXISTS student_login_sessions (',
    ' activity_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,',
    ' user_id ', @student_activity_user_id_type, ' NOT NULL,',
    ' started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,',
    ' last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,',
    ' ended_at TIMESTAMP NULL DEFAULT NULL,',
    ' PRIMARY KEY (activity_id),',
    ' KEY idx_student_login_sessions_user_started (user_id, started_at),',
    ' KEY idx_student_login_sessions_started_ended (started_at, ended_at),',
    ' CONSTRAINT fk_student_login_sessions_user FOREIGN KEY (user_id)',
    ' REFERENCES users (user_id) ON DELETE CASCADE',
    ') ENGINE=InnoDB'
);
PREPARE student_login_sessions_statement FROM @student_login_sessions_migration;
EXECUTE student_login_sessions_statement;
DEALLOCATE PREPARE student_login_sessions_statement;

CREATE TABLE IF NOT EXISTS student_activity_tracking (
    tracking_id TINYINT UNSIGNED NOT NULL,
    tracking_started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tracking_id)
) ENGINE=InnoDB;

INSERT IGNORE INTO student_activity_tracking (tracking_id)
VALUES (1);

-- ===== 12_business_administration_category.sql =====
USE python_app;

UPDATE resources
SET resource_category = 'Business Administration'
WHERE resource_category = 'Business Studies';

-- ===== 13_community_chat.sql =====
USE python_app;

-- Match foreign-key column types to existing installs, which may predate the current BIGINT schema.
SET @community_messages_community_id_type = (
    SELECT COLUMN_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'communities'
      AND COLUMN_NAME = 'community_id'
);
SET @community_messages_user_id_type = (
    SELECT COLUMN_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'users'
      AND COLUMN_NAME = 'user_id'
);
SET @community_messages_sql = CONCAT(
    'CREATE TABLE IF NOT EXISTS community_messages (',
    'message_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,',
    'community_id ', @community_messages_community_id_type, ' NOT NULL,',
    'author_id ', @community_messages_user_id_type, ' NOT NULL,',
    'legacy_post_id BIGINT UNSIGNED NULL,',
    'content TEXT NOT NULL,',
    'message_type ENUM(''message'', ''announcement'') NOT NULL DEFAULT ''message'',',
    'is_highlighted BOOLEAN NOT NULL DEFAULT FALSE,',
    'is_pinned BOOLEAN NOT NULL DEFAULT FALSE,',
    'pinned_by ', @community_messages_user_id_type, ' NULL,',
    'pinned_at TIMESTAMP NULL DEFAULT NULL,',
    'created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,',
    'updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,',
    'PRIMARY KEY (message_id),',
    'UNIQUE KEY uq_community_messages_legacy_post (legacy_post_id),',
    'KEY idx_community_messages_created (community_id, message_id),',
    'KEY idx_community_messages_pinned (community_id, pinned_at),',
    'CONSTRAINT fk_community_messages_community FOREIGN KEY (community_id) ',
    'REFERENCES communities (community_id) ON DELETE CASCADE,',
    'CONSTRAINT fk_community_messages_author FOREIGN KEY (author_id) ',
    'REFERENCES users (user_id) ON DELETE RESTRICT,',
    'CONSTRAINT fk_community_messages_pinner FOREIGN KEY (pinned_by) ',
    'REFERENCES users (user_id) ON DELETE SET NULL',
    ') ENGINE=InnoDB'
);
PREPARE create_community_messages FROM @community_messages_sql;
EXECUTE create_community_messages;
DEALLOCATE PREPARE create_community_messages;

INSERT IGNORE INTO community_messages
    (community_id, author_id, legacy_post_id, content, message_type, created_at, updated_at)
SELECT community_id, author_id, post_id, content, 'announcement', created_at, updated_at
FROM community_posts;

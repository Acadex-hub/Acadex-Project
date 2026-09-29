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
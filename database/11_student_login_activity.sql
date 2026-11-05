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

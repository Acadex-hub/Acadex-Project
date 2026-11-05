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

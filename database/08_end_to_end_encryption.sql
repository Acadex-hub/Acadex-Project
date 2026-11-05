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

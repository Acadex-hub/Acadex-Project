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

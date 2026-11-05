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

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
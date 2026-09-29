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
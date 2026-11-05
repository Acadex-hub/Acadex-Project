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

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

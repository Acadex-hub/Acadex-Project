USE python_app;

SET @community_group_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'communities'
      AND COLUMN_NAME = 'community_group'
);
SET @community_group_migration = IF(
    @community_group_exists = 0,
    'ALTER TABLE communities ADD COLUMN community_group VARCHAR(100) NOT NULL DEFAULT ''IT Communities'' AFTER description',
    'SELECT 1'
);
PREPARE community_group_statement FROM @community_group_migration;
EXECUTE community_group_statement;
DEALLOCATE PREPARE community_group_statement;

INSERT IGNORE INTO communities
    (community_key, course_id, created_by, name, description, community_group,
     community_category, visibility, status)
VALUES
    ('ba-accounting', NULL, NULL, 'Accounting', 'Discuss accounting principles, financial reporting, and practical problem-solving.', 'BA Communities', 'Accounting', 'public', 'active'),
    ('ba-commercial-law', NULL, NULL, 'Commercial law', 'Explore commercial law concepts and their application in business.', 'BA Communities', 'Commercial law', 'public', 'active'),
    ('ba-business-management', NULL, NULL, 'Business Management', 'Share ideas on managing people, organizations, and business operations.', 'BA Communities', 'Business Management', 'public', 'active'),
    ('ba-supply-chain', NULL, NULL, 'Supply Chain', 'Discuss procurement, logistics, and supply-chain management.', 'BA Communities', 'Supply Chain', 'public', 'active'),
    ('ba-economics', NULL, NULL, 'Economics', 'Explore economic theory, policy, markets, and current issues.', 'BA Communities', 'Economics', 'public', 'active'),
    ('ba-information-systems', NULL, NULL, 'Information Systems', 'Discuss how information systems support business processes and decisions.', 'BA Communities', 'Information Systems', 'public', 'active'),
    ('ba-business-ethics', NULL, NULL, 'Business Ethics', 'Discuss ethical decision-making and responsibility in business.', 'BA Communities', 'Business Ethics', 'public', 'active'),
    ('ba-industrial-phsycology', NULL, NULL, 'Industrial Phsycology', 'Explore psychology in the workplace and organizational behavior.', 'BA Communities', 'Industrial Phsycology', 'public', 'active'),
    ('ba-statistics', NULL, NULL, 'Statistics', 'Study statistical methods and their application to business data.', 'BA Communities', 'Statistics', 'public', 'active');

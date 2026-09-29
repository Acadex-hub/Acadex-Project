USE python_app;

CREATE TABLE IF NOT EXISTS friendships (
    user_id_a BIGINT UNSIGNED NOT NULL,
    user_id_b BIGINT UNSIGNED NOT NULL,
    requested_by BIGINT UNSIGNED NOT NULL,
    status ENUM('pending', 'accepted', 'rejected', 'blocked') NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id_a, user_id_b),
    KEY idx_friendships_b_status (user_id_b, status),
    CONSTRAINT chk_friendship_pair CHECK (user_id_a < user_id_b),
    CONSTRAINT chk_friendship_requester CHECK (requested_by = user_id_a OR requested_by = user_id_b),
    CONSTRAINT fk_friendships_user_a FOREIGN KEY (user_id_a)
        REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_friendships_user_b FOREIGN KEY (user_id_b)
        REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_friendships_requester FOREIGN KEY (requested_by)
        REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS communities (
    community_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    course_id BIGINT UNSIGNED NULL,
    created_by BIGINT UNSIGNED NOT NULL,
    name VARCHAR(180) NOT NULL,
    description TEXT NULL,
    visibility ENUM('public', 'private') NOT NULL DEFAULT 'public',
    status ENUM('active', 'archived') NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (community_id),
    KEY idx_communities_course_status (course_id, status),
    CONSTRAINT fk_communities_course FOREIGN KEY (course_id)
        REFERENCES courses (course_id) ON DELETE SET NULL,
    CONSTRAINT fk_communities_creator FOREIGN KEY (created_by)
        REFERENCES users (user_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS community_members (
    community_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    member_role ENUM('owner', 'moderator', 'member') NOT NULL DEFAULT 'member',
    status ENUM('invited', 'active', 'left', 'banned') NOT NULL DEFAULT 'active',
    joined_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (community_id, user_id),
    KEY idx_community_members_user_status (user_id, status),
    CONSTRAINT fk_community_members_community FOREIGN KEY (community_id)
        REFERENCES communities (community_id) ON DELETE CASCADE,
    CONSTRAINT fk_community_members_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS community_posts (
    post_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    community_id BIGINT UNSIGNED NOT NULL,
    author_id BIGINT UNSIGNED NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (post_id),
    KEY idx_community_posts_created (community_id, created_at),
    CONSTRAINT fk_community_posts_community FOREIGN KEY (community_id)
        REFERENCES communities (community_id) ON DELETE CASCADE,
    CONSTRAINT fk_community_posts_author FOREIGN KEY (author_id)
        REFERENCES users (user_id) ON DELETE RESTRICT
) ENGINE=InnoDB;
-- ============================================================
-- META SCRAPER ΓÇö Initial Schema
-- Run once on a fresh database to initialize all tables.
-- ============================================================

-- ΓöÇΓöÇ 1. schedule_state ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
-- Owned by C1. Written by C2 (orchestrator) and C5 (recovery).
CREATE TABLE IF NOT EXISTS schedule_state (
    job_id          VARCHAR(50)  PRIMARY KEY,
    status          VARCHAR(20)  NOT NULL DEFAULT 'IDLE',
                    -- 'IDLE' | 'RUNNING' | 'PAUSED' | 'FAILED'
    last_cursor     VARCHAR(512),
    current_post_id VARCHAR(50),
    heartbeat_at    TIMESTAMP WITH TIME ZONE,
    resume_at       TIMESTAMP WITH TIME ZONE,
    last_success_at TIMESTAMP WITH TIME ZONE,
    pause_attempt   INTEGER      NOT NULL DEFAULT 0,
    error_log       TEXT
);

-- Seed the single job row used by the scraper.
INSERT INTO schedule_state (job_id, status)
VALUES ('meta_page_scraper', 'IDLE')
ON CONFLICT (job_id) DO NOTHING;

-- ΓöÇΓöÇ 2. active_posts ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
-- Owned by C1. Written by C3 (discovery) and C4 (validity checker).
CREATE TABLE IF NOT EXISTS active_posts (
    post_id               VARCHAR(50)  PRIMARY KEY,
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL,
    status                VARCHAR(20)  NOT NULL DEFAULT 'active',
                          -- 'active' | 'archived' | 'invalid'
    last_comment_cursor   VARCHAR(512),
    last_scraped_at       TIMESTAMP WITH TIME ZONE,
    archived_at           TIMESTAMP WITH TIME ZONE
);

-- ΓöÇΓöÇ 3. comments ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
-- Owned by C1. Written by C4 (persistence, like_sync).
CREATE TABLE IF NOT EXISTS comments (
    comment_id              VARCHAR(50)  PRIMARY KEY,
    post_id                 VARCHAR(50)  NOT NULL,
    text_content            TEXT         NOT NULL,
    like_count              INTEGER      NOT NULL DEFAULT 0,
    created_at              TIMESTAMP WITH TIME ZONE NOT NULL,
    is_reply                BOOLEAN      NOT NULL DEFAULT FALSE,
    processed_for_sentiment BOOLEAN      NOT NULL DEFAULT FALSE,
    scraped_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ΓöÇΓöÇ Permissions ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
-- Run these as a superuser after creating the 'scraper' role:
-- CREATE ROLE scraper WITH LOGIN PASSWORD 'changeme';
-- GRANT CONNECT ON DATABASE scraper_db TO scraper;
-- GRANT USAGE ON SCHEMA public TO scraper;
-- GRANT SELECT, INSERT, UPDATE ON schedule_state TO scraper;
-- GRANT SELECT, INSERT, UPDATE ON active_posts TO scraper;
-- GRANT SELECT, INSERT, UPDATE ON comments TO scraper;
-- REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM scraper;

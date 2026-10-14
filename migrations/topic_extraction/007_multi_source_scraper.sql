-- Migration 007: Multi-source scraper support
-- Enables multiple Facebook pages and Instagram accounts

-- ============================================================================
-- 1. scraping_sources: registry of all connected pages/accounts
-- ============================================================================
CREATE TABLE IF NOT EXISTS scraping_sources (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(20) NOT NULL CHECK (platform IN ('facebook', 'instagram')),
    external_id VARCHAR(255) NOT NULL,               -- Facebook page_id or Instagram account_id
    name VARCHAR(255),                                -- Human-readable name
    access_token TEXT,                                -- Per-page token (nullable if global token used)
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    health_status VARCHAR(20) NOT NULL DEFAULT 'unknown' CHECK (health_status IN ('unknown', 'healthy', 'error', 'disabled')),
    last_error TEXT,
    last_error_at TIMESTAMPTZ,
    last_scraped_at TIMESTAMPTZ,
    total_comments_scraped INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (platform, external_id)
);

CREATE INDEX idx_scraping_sources_platform ON scraping_sources(platform);
CREATE INDEX idx_scraping_sources_active ON scraping_sources(is_active);
CREATE INDEX idx_scraping_sources_health ON scraping_sources(health_status);

-- ============================================================================
-- 2. scraping_job_instances: per-source APScheduler job tracking
-- ============================================================================
CREATE TABLE IF NOT EXISTS scraping_job_instances (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES scraping_sources(id) ON DELETE CASCADE,
    job_name VARCHAR(255) NOT NULL UNIQUE,            -- e.g. "facebook_scraper_1046104841919615"
    status VARCHAR(20) NOT NULL DEFAULT 'idle' CHECK (status IN ('idle', 'running', 'paused', 'error')),
    next_run_time TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    last_duration_ms BIGINT,
    error_count INTEGER NOT NULL DEFAULT 0,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scraping_jobs_source ON scraping_job_instances(source_id);
CREATE INDEX idx_scraping_jobs_status ON scraping_job_instances(status);

-- ============================================================================
-- 3. Alter active_posts: link to scraping source
-- ============================================================================
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'active_posts' AND column_name = 'source_id') THEN
        ALTER TABLE active_posts ADD COLUMN source_id INTEGER REFERENCES scraping_sources(id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_active_posts_source_id ON active_posts(source_id);

-- ============================================================================
-- 3b. Alter comments: store originating platform for dashboard filters
-- ============================================================================
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'comments' AND column_name = 'source') THEN
        ALTER TABLE comments ADD COLUMN source VARCHAR(20) DEFAULT 'facebook';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_comments_source ON comments(source);

-- ============================================================================
-- 4. Alter schedule_state: per-source tracking
-- ============================================================================
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'schedule_state' AND column_name = 'source_id') THEN
        ALTER TABLE schedule_state ADD COLUMN source_id INTEGER REFERENCES scraping_sources(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'schedule_state' AND column_name = 'platform') THEN
        ALTER TABLE schedule_state ADD COLUMN platform VARCHAR(20);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_schedule_state_source ON schedule_state(source_id);

-- ============================================================================
-- 5. Backfill: create scraping_source for existing Facebook page
-- ============================================================================
DO $$
DECLARE
    v_source_id INTEGER;
BEGIN
    -- Only seed if the table is empty
    IF NOT EXISTS (SELECT 1 FROM scraping_sources) THEN
        INSERT INTO scraping_sources (
            platform, external_id, name, access_token, is_active,
            health_status, last_scraped_at, total_comments_scraped
        )
        SELECT
            'facebook',
            COALESCE(current_setting('app.meta_page_id', true), '1046104841919615'),
            'Algérie Télécom',
            NULL,  -- token stays in env for now
            TRUE,
            'healthy',
            (SELECT last_scraped_at FROM schedule_state WHERE job_id = 'meta_page_scraper' LIMIT 1),
            (SELECT COUNT(*) FROM comments WHERE source = 'meta' OR source = 'facebook')
        WHERE EXISTS (SELECT 1 FROM schedule_state WHERE job_id = 'meta_page_scraper');

        -- Get the newly inserted id
        SELECT id INTO v_source_id FROM scraping_sources WHERE platform = 'facebook' LIMIT 1;

        -- Backfill active_posts
        UPDATE active_posts
        SET source_id = v_source_id
        WHERE source_id IS NULL;

        -- Backfill schedule_state
        UPDATE schedule_state
        SET source_id = v_source_id,
            platform = 'facebook',
            job_id = 'facebook_scraper_' || (SELECT external_id FROM scraping_sources WHERE id = v_source_id)
        WHERE job_id = 'meta_page_scraper';
    END IF;
END $$;

-- ============================================================================
-- 6. Backfill: update comments.source from 'meta' to 'facebook'
-- ============================================================================
UPDATE comments
SET source = 'facebook'
WHERE source = 'meta';

-- ============================================================================
-- 7. Add NOT NULL constraint on active_posts.source_id after backfill
-- ============================================================================
-- (Only if all rows have been backfilled — if not, skip this)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM active_posts WHERE source_id IS NULL LIMIT 1
    ) THEN
        RAISE NOTICE 'Some active_posts rows still have NULL source_id; skipping NOT NULL constraint';
    ELSE
        ALTER TABLE active_posts ALTER COLUMN source_id SET NOT NULL;
    END IF;
END $$;

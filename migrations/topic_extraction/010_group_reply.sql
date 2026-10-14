-- Migration 010: Group Reply (engagement plane)
-- Adds the write-path tables (campaigns + per-page job queues + shared rate view)
-- and write-permission columns on scraping_sources.
-- Idempotent (IF NOT EXISTS / guarded ALTER) per the platform migration convention.

BEGIN;

-- ============================================================================
-- 1. scraping_sources: write-permission awareness (R8)
-- ============================================================================
ALTER TABLE scraping_sources ADD COLUMN IF NOT EXISTS can_reply             BOOLEAN     NOT NULL DEFAULT false;
ALTER TABLE scraping_sources ADD COLUMN IF NOT EXISTS reply_perm_checked_at TIMESTAMPTZ;
ALTER TABLE scraping_sources ADD COLUMN IF NOT EXISTS reply_perm_error      TEXT;

-- ============================================================================
-- 2. reply_campaigns: one row per "click Reply"
-- ============================================================================
CREATE TABLE IF NOT EXISTS reply_campaigns (
    id              BIGSERIAL    PRIMARY KEY,
    created_by      INTEGER      REFERENCES users(id),
    reply_text      TEXT         NOT NULL,
    filter_snapshot JSONB        NOT NULL DEFAULT '{}',
    total_targets   INTEGER      NOT NULL DEFAULT 0,
    counts          JSONB        NOT NULL DEFAULT '{}',
    status          VARCHAR(16)  NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','in_progress','completed','partial','failed')),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_reply_campaigns_created_at ON reply_campaigns (created_at DESC);

-- ============================================================================
-- 3. reply_jobs: the per-comment queue items (the 140 logical queues live here,
--    partitioned by source_id)
-- ============================================================================
CREATE TABLE IF NOT EXISTS reply_jobs (
    id            BIGSERIAL    PRIMARY KEY,
    campaign_id   BIGINT       NOT NULL REFERENCES reply_campaigns(id) ON DELETE CASCADE,
    comment_id    VARCHAR(50)  NOT NULL,
    source_id     INTEGER      NOT NULL REFERENCES scraping_sources(id),
    post_id       VARCHAR(50)  NOT NULL,
    reply_text    TEXT         NOT NULL,
    scheduled_for TIMESTAMPTZ  NOT NULL,
    status        VARCHAR(12)  NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','sending','sent','skipped','failed')),
    attempts      INTEGER      NOT NULL DEFAULT 0,
    claimed_at    TIMESTAMPTZ,
    sent_at       TIMESTAMPTZ,
    meta_reply_id VARCHAR(64),
    error_code    VARCHAR(40),
    error_message TEXT,
    skip_reason   VARCHAR(80),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Per-page FIFO draining (the core dispatcher hot path).
CREATE INDEX IF NOT EXISTS ix_reply_jobs_queue
    ON reply_jobs (source_id, status, scheduled_for, id);

-- Capacity accounting reads per-day pending load per page.
CREATE INDEX IF NOT EXISTS ix_reply_jobs_page_day
    ON reply_jobs (source_id, scheduled_for)
    WHERE status IN ('pending','sending');

-- R10 hard guarantee: a comment can never have two live/sent jobs.
CREATE UNIQUE INDEX IF NOT EXISTS uq_reply_jobs_comment_live
    ON reply_jobs (comment_id)
    WHERE status IN ('pending','sending','sent');

-- ============================================================================
-- 4. page_rate_state: shared per-page usage view (scrape/reply coordination).
--    Created now; written by the scraper + reply dispatcher in the send-path pass.
-- ============================================================================
CREATE TABLE IF NOT EXISTS page_rate_state (
    source_id         INTEGER      PRIMARY KEY REFERENCES scraping_sources(id) ON DELETE CASCADE,
    app_usage_pct     NUMERIC(5,2) NOT NULL DEFAULT 0.0,
    observed_at       TIMESTAMPTZ,
    daily_window_date DATE,
    used_today        INTEGER      NOT NULL DEFAULT 0
);

COMMIT;

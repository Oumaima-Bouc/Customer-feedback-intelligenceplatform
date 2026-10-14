-- 001_add_topic_sentiment_to_comments.sql
-- Adds enrichment columns and pipeline_checkpoints table.
-- Safe to run multiple times (idempotent).

BEGIN;

-- Add enrichment columns to comments table
ALTER TABLE comments
    ADD COLUMN IF NOT EXISTS topic TEXT,
    ADD COLUMN IF NOT EXISTS sentiment VARCHAR(16),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Checkpoint table for keyset-resume
CREATE TABLE IF NOT EXISTS pipeline_checkpoints (
    checkpoint_key      TEXT PRIMARY KEY,
    last_comment_id     BIGINT NOT NULL,
    last_run_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_window_start   TIMESTAMPTZ NULL,
    last_window_end     TIMESTAMPTZ NULL
);

COMMIT;

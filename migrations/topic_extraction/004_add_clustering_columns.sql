-- 004_add_clustering_columns.sql
-- Adds cluster_id, topic_label, and fallback_used columns for the new
-- sentiment-first + clustering + LLM labeling architecture.
-- Also fixes pipeline_checkpoints.last_comment_id type (BIGINT -> TEXT)
-- to match comments.comment_id which is VARCHAR(50).
-- Safe to run multiple times (idempotent).

BEGIN;

-- New columns for clustering pipeline
ALTER TABLE comments
    ADD COLUMN IF NOT EXISTS cluster_id INTEGER,
    ADD COLUMN IF NOT EXISTS topic_label TEXT,
    ADD COLUMN IF NOT EXISTS fallback_used BOOLEAN DEFAULT FALSE;

-- Fix checkpoint table: last_comment_id must be TEXT to match varchar comment_id
ALTER TABLE pipeline_checkpoints
    ALTER COLUMN last_comment_id TYPE TEXT USING last_comment_id::TEXT;

-- Index for cluster-based queries
CREATE INDEX IF NOT EXISTS idx_comments_cluster_id
    ON comments (cluster_id);

-- Index for fallback monitoring
CREATE INDEX IF NOT EXISTS idx_comments_fallback_used
    ON comments (fallback_used)
    WHERE fallback_used = TRUE;

-- Composite index for cluster + sentiment reporting
CREATE INDEX IF NOT EXISTS idx_comments_cluster_sentiment
    ON comments (cluster_id, sentiment);

COMMIT;

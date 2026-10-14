-- 002_add_indexes.sql
-- Performance indexes for the comment enrichment pipeline.

BEGIN;

-- Primary pagination index (keyset pagination)
CREATE INDEX IF NOT EXISTS idx_comments_created_at_comment_id
    ON comments (created_at, comment_id);

-- Reporting indexes
CREATE INDEX IF NOT EXISTS idx_comments_topic
    ON comments (topic);

CREATE INDEX IF NOT EXISTS idx_comments_sentiment
    ON comments (sentiment);

CREATE INDEX IF NOT EXISTS idx_comments_topic_sentiment
    ON comments (topic, sentiment);

-- Partial index for unprocessed rows — dramatically speeds up fetch_batch
-- when PIPELINE_PROCESS_ONLY_UNCLASSIFIED=true
CREATE INDEX IF NOT EXISTS idx_comments_unprocessed
    ON comments (comment_id)
    WHERE topic IS NULL OR sentiment IS NULL;

COMMIT;

-- Migration 011: Label Feedback (human-in-the-loop topic/sentiment correction)
-- Adds correction-protection columns on comments, the training-capture table
-- label_feedback, and a persistent topics registry. Idempotent.

BEGIN;

-- ============================================================================
-- 1. comments: human-correction protection + fast-read flags
-- ============================================================================
ALTER TABLE comments ADD COLUMN IF NOT EXISTS human_verified BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE comments ADD COLUMN IF NOT EXISTS verified_by    INTEGER REFERENCES users(id);
ALTER TABLE comments ADD COLUMN IF NOT EXISTS verified_at    TIMESTAMPTZ;

-- Protect corrected rows from the enrichment pipeline (cheap skip).
CREATE INDEX IF NOT EXISTS ix_comments_human_verified
    ON comments (human_verified) WHERE human_verified;
-- Merge case/space topic variants in live aggregates without a feedback join (Pass 2).
CREATE INDEX IF NOT EXISTS ix_comments_topic_norm ON comments (lower(btrim(topic)));
-- Trend chart range scans by comment day (Pass 2) are served by the existing
-- idx_comments_created_at_comment_id (migration 002); date_trunc() on timestamptz
-- is not IMMUTABLE so it cannot be an index expression.

-- ============================================================================
-- 2. label_feedback: write-only training capture (one row per corrected comment)
-- ============================================================================
CREATE TABLE IF NOT EXISTS label_feedback (
    id                 BIGSERIAL    PRIMARY KEY,
    comment_id         VARCHAR(50)  NOT NULL,
    pipeline_topic     TEXT,
    pipeline_sentiment VARCHAR(16),
    human_topic        TEXT,
    human_sentiment    VARCHAR(16),
    human_topic_key    TEXT,
    topic_changed      BOOLEAN      NOT NULL DEFAULT false,
    sentiment_changed  BOOLEAN      NOT NULL DEFAULT false,
    user_id            INTEGER      REFERENCES users(id),
    batch_id           UUID,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- First-writer-wins: a comment can be corrected at most once, ever (R3).
CREATE UNIQUE INDEX IF NOT EXISTS uq_label_feedback_comment ON label_feedback (comment_id);
-- Export scan ordered by time (off the hot path).
CREATE INDEX IF NOT EXISTS ix_label_feedback_created ON label_feedback (created_at);

-- ============================================================================
-- 3. topics: persistent canonical registry (counts are derived live, never stored)
-- ============================================================================
CREATE TABLE IF NOT EXISTS topics (
    id            SERIAL       PRIMARY KEY,
    topic_key     TEXT         NOT NULL UNIQUE,
    display_label TEXT         NOT NULL,
    origin        VARCHAR(8)   NOT NULL DEFAULT 'pipeline'
                  CHECK (origin IN ('pipeline', 'human')),
    created_by    INTEGER      REFERENCES users(id),
    canonical_id  INTEGER      REFERENCES topics(id),  -- similarity-mapping seam (NULL in MVP)
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Backfill the registry from existing (pipeline) topics. The display label is the
-- first-seen casing for each normalized key.
INSERT INTO topics (topic_key, display_label, origin)
SELECT DISTINCT ON (lower(btrim(topic)))
       lower(btrim(topic)) AS topic_key,
       btrim(topic)        AS display_label,
       'pipeline'
FROM comments
WHERE topic IS NOT NULL AND btrim(topic) <> ''
ORDER BY lower(btrim(topic)), btrim(topic)
ON CONFLICT (topic_key) DO NOTHING;

COMMIT;

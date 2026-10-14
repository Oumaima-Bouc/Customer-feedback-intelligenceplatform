-- ============================================================
-- Word Cloud Snapshot — live word frequency + sentiment scores
-- Overwritten on every ML pipeline run (no history).
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS word_cloud_snapshot (
    word            VARCHAR(100)    PRIMARY KEY,
    frequency       INTEGER         NOT NULL,
    positive_pct    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    neutral_pct     DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    negative_pct    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    source          VARCHAR(20)     NOT NULL,
    category        VARCHAR(50),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_word_cloud_frequency
    ON word_cloud_snapshot (frequency DESC);

CREATE INDEX IF NOT EXISTS idx_word_cloud_source
    ON word_cloud_snapshot (source);

COMMIT;

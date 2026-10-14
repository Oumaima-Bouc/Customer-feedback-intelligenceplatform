-- 003_add_topic_daily_tracking.sql
-- Stores per-topic aggregated counts + sentiment percentages per run date.
-- Used by frontend to plot topic development over time.

BEGIN;

CREATE TABLE IF NOT EXISTS topic_daily_tracking (
    id              BIGSERIAL PRIMARY KEY,
    run_date        DATE NOT NULL,
    topic           TEXT NOT NULL,
    comment_count   INTEGER NOT NULL DEFAULT 0,
    positive_pct    NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    neutral_pct     NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    negative_pct    NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_topic_daily_tracking_date_topic UNIQUE (run_date, topic)
);

-- Index for time-series queries (frontend charts)
CREATE INDEX IF NOT EXISTS idx_topic_daily_tracking_run_date
    ON topic_daily_tracking (run_date);

CREATE INDEX IF NOT EXISTS idx_topic_daily_tracking_topic_date
    ON topic_daily_tracking (topic, run_date);

COMMIT;

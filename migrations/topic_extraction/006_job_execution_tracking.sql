-- ============================================================
-- Job Execution Tracking — centralized logging for all jobs
-- Stores per-run execution records + structured log entries.
-- Dashboard shows last 24h; archiving moves older to files.
-- ============================================================

BEGIN;

-- Parent table: one row per job execution (scraper run, ML pipeline run, etc.)
CREATE TABLE IF NOT EXISTS job_executions (
    id              BIGSERIAL       PRIMARY KEY,
    job_name        VARCHAR(100)    NOT NULL,
    service         VARCHAR(50)     NOT NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'running',
    started_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMP WITH TIME ZONE,
    duration_ms     INTEGER,
    records_in      INTEGER         DEFAULT 0,
    records_out     INTEGER         DEFAULT 0,
    error_count     INTEGER         DEFAULT 0,
    error_message   TEXT,
    metadata        JSONB           DEFAULT '{}',
    CONSTRAINT chk_job_status CHECK (status IN ('running', 'completed', 'failed', 'partial'))
);

CREATE INDEX IF NOT EXISTS idx_job_exec_job_name     ON job_executions (job_name);
CREATE INDEX IF NOT EXISTS idx_job_exec_started_at   ON job_executions (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_exec_service      ON job_executions (service);
CREATE INDEX IF NOT EXISTS idx_job_exec_status       ON job_executions (status);

-- Child table: structured log entries per execution
CREATE TABLE IF NOT EXISTS job_log_entries (
    id              BIGSERIAL       PRIMARY KEY,
    execution_id    BIGINT          NOT NULL REFERENCES job_executions(id) ON DELETE CASCADE,
    logged_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    level           VARCHAR(10)     NOT NULL DEFAULT 'INFO',
    event           VARCHAR(200)    NOT NULL,
    message         TEXT,
    details         JSONB           DEFAULT '{}',
    CONSTRAINT chk_log_level CHECK (level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'))
);

CREATE INDEX IF NOT EXISTS idx_job_log_exec_id    ON job_log_entries (execution_id);
CREATE INDEX IF NOT EXISTS idx_job_log_logged_at  ON job_log_entries (logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_log_level      ON job_log_entries (level);

COMMIT;

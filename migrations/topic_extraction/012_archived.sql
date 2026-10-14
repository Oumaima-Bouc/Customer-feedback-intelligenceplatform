-- Migration 012: "last successful run" data scoping.
-- Comments belong to the latest successful scrape run until a newer run supersedes
-- them. Superseded comments are flagged `archived` (the producer flips this on a new
-- successful run); every dashboard read scopes to `NOT archived` so the UI always
-- shows exactly the last run's data and is never empty between runs. Idempotent.

BEGIN;

ALTER TABLE comments ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT false;

-- All current dashboard aggregates filter on the live (non-archived) set.
CREATE INDEX IF NOT EXISTS ix_comments_live ON comments (created_at) WHERE NOT archived;

COMMIT;

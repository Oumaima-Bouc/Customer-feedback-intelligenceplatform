-- Migration 009: Force password change for the default admin
-- Adds a password_change_required flag and forces any account still using the
-- well-known default password ('admin123') to rotate it on next login.
-- Idempotent: the UPDATE only matches the unchanged default bcrypt hash, so it
-- will not re-flag an admin who has already rotated their password.

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_change_required BOOLEAN NOT NULL DEFAULT FALSE;

-- Flag ONLY accounts that still carry the seeded default hash (bcrypt('admin123')).
UPDATE users
SET password_change_required = TRUE
WHERE password_hash = '$2b$12$96U2YfCxPl.MnPHs7hw9uO0jCJgZk4KxJQV1AqxcXxQKAOXZJQVgK';

COMMIT;

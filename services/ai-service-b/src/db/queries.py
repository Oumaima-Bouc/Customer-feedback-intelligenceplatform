"""
C1 - Infrastructure & Configuration
db/queries.py
Single source of truth for ALL SQL in the system.
No raw SQL strings exist outside this file.
Every constant is a named, documented SQL template.
"""


class Queries:
    """
    Namespaced SQL constants.
    Parameters are positional ($1, $2, ...) - asyncpg style.
    """

    # -- schedule_state --

    LOCK_JOB = """
        SELECT job_id, status, last_cursor, current_post_id,
               heartbeat_at, resume_at, last_success_at, pause_attempt
        FROM   schedule_state
        WHERE  job_id = $1
        FOR UPDATE SKIP LOCKED
    """

    ENSURE_JOB_ROW = """
        INSERT INTO schedule_state (job_id, status, source_id, platform)
        VALUES ($1, 'IDLE', $2, $3)
        ON CONFLICT (job_id) DO NOTHING
    """

    SET_RUNNING = """
        UPDATE schedule_state
        SET    status       = 'RUNNING',
               heartbeat_at = NOW(),
               error_log    = NULL
        WHERE  job_id = $1
    """

    SET_IDLE = """
        UPDATE schedule_state
        SET    status          = 'IDLE',
               last_success_at = NOW(),
               pause_attempt   = 0,
               last_cursor     = NULL,
               current_post_id = NULL,
               resume_at       = NULL
        WHERE  job_id = $1
    """

    SET_PAUSED = """
        UPDATE schedule_state
        SET    status          = 'PAUSED',
               last_cursor     = $2,
               current_post_id = $3,
               resume_at       = $4,
               pause_attempt   = $5
        WHERE  job_id = $1
    """

    SET_FAILED = """
        UPDATE schedule_state
        SET    status    = 'FAILED',
               error_log = $2
        WHERE  job_id = $1
    """

    UPDATE_HEARTBEAT = """
        UPDATE schedule_state
        SET    heartbeat_at = NOW()
        WHERE  job_id = $1
    """

    GET_STATE = """
        SELECT job_id, status, last_cursor, current_post_id,
               heartbeat_at, resume_at, last_success_at, pause_attempt, error_log
        FROM   schedule_state
        WHERE  job_id = $1
    """

    RESET_ZOMBIE = """
        UPDATE schedule_state
        SET    status = 'IDLE'
        WHERE  job_id = $1
          AND  status = 'RUNNING'
          AND  heartbeat_at < NOW() - INTERVAL '5 minutes'
    """

    # -- active_posts --

    UPSERT_POST = """
        INSERT INTO active_posts (post_id, created_at, status, source_id)
        VALUES ($1, $2, 'active', $3)
        ON CONFLICT (post_id) DO UPDATE
            SET status = CASE
                    WHEN active_posts.status = 'invalid' THEN 'invalid'
                    ELSE 'active'
                END,
                source_id = COALESCE(active_posts.source_id, EXCLUDED.source_id)
    """

    ARCHIVE_OLD_POSTS = """
        UPDATE active_posts
        SET    status      = 'archived',
               archived_at = NOW()
        WHERE  created_at < NOW() - ($1 || ' hours')::INTERVAL
          AND  status = 'active'
    """

    GET_ACTIVE_POSTS = """
        SELECT post_id, last_scraped_at, last_comment_cursor
        FROM   active_posts
        WHERE  status = 'active'
          AND  ($2::INTEGER IS NULL OR source_id = $2)
        ORDER BY created_at DESC
        LIMIT  $1
    """

    MARK_POST_INVALID = """
        UPDATE active_posts
        SET    status = 'invalid'
        WHERE  post_id = $1
    """

    UPDATE_POST_CURSOR = """
        UPDATE active_posts
        SET    last_comment_cursor = $2,
               last_scraped_at     = NOW()
        WHERE  post_id = $1
    """

    # -- comments --

    UPSERT_COMMENT = """
        INSERT INTO comments
            (comment_id, post_id, text_content, like_count, created_at, is_reply, source)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (comment_id) DO UPDATE
            SET text_content = EXCLUDED.text_content,
                like_count   = EXCLUDED.like_count,
                source       = EXCLUDED.source
    """

    UPDATE_LIKE_COUNT = """
        UPDATE comments
        SET    like_count = $2
        WHERE  comment_id = $1
    """

    GET_COMMENT_IDS_FOR_LIKE_SYNC = """
        SELECT comment_id
        FROM   comments
        WHERE  post_id = ANY($1::VARCHAR[])
        ORDER BY like_count DESC
        LIMIT  $2
    """

    GET_UNPROCESSED_COMMENTS = """
        SELECT comment_id, post_id, text_content, like_count,
               created_at, is_reply, scraped_at
        FROM   comments
        WHERE  processed_for_sentiment = FALSE
        ORDER BY scraped_at ASC
    """

    MARK_COMMENTS_PROCESSED = """
        UPDATE comments
        SET    processed_for_sentiment = TRUE
        WHERE  comment_id = ANY($1::VARCHAR[])
    """

    DELETE_PROCESSED_COMMENTS = """
        DELETE FROM comments
        WHERE  processed_for_sentiment = TRUE
          AND  comment_id = ANY($1::VARCHAR[])
    """

"""
All SQL for the reply enqueue path as named constants (house rule: no raw SQL
strings elsewhere). psycopg2 named-parameter style (%(name)s).

The repliability predicate (R8/R9/R10) is identical in both selection modes:
  - is_reply = false                         (not a reply-of-a-reply, R9)
  - active_posts.status = 'active'           (post not archived/deleted, R9)
  - scraping_sources.can_reply = true        (page has write permission, R8)
  - no live reply_job for the comment         (no duplicates, R10)
"""


class Q:
    ELIGIBLE_BY_IDS = """
        SELECT c.comment_id, c.post_id, ap.source_id
        FROM comments c
        JOIN active_posts ap ON ap.post_id = c.post_id AND ap.status = 'active'
        JOIN scraping_sources ss ON ss.id = ap.source_id AND ss.can_reply = TRUE
        WHERE c.is_reply = FALSE
          AND c.comment_id = ANY(%(ids)s)
          AND NOT EXISTS (
              SELECT 1 FROM reply_jobs rj
              WHERE rj.comment_id = c.comment_id
                AND rj.status IN ('pending','sending','sent')
          )
    """

    ELIGIBLE_BY_FILTER = """
        SELECT c.comment_id, c.post_id, ap.source_id
        FROM comments c
        JOIN active_posts ap ON ap.post_id = c.post_id AND ap.status = 'active'
        JOIN scraping_sources ss ON ss.id = ap.source_id AND ss.can_reply = TRUE
        WHERE c.is_reply = FALSE
          AND c.topic IS NOT NULL
          AND (%(topic)s = '' OR c.topic = %(topic)s)
          AND (%(sentiment)s = '' OR c.sentiment = %(sentiment)s)
          AND NOT EXISTS (
              SELECT 1 FROM reply_jobs rj
              WHERE rj.comment_id = c.comment_id
                AND rj.status IN ('pending','sending','sent')
          )
    """

    COUNT_REQUESTED_BY_IDS = """
        SELECT COUNT(*) FROM comments WHERE comment_id = ANY(%(ids)s)
    """

    COUNT_REQUESTED_BY_FILTER = """
        SELECT COUNT(*) FROM comments c
        WHERE c.topic IS NOT NULL
          AND (%(topic)s = '' OR c.topic = %(topic)s)
          AND (%(sentiment)s = '' OR c.sentiment = %(sentiment)s)
    """

    COUNT_ALREADY_BY_IDS = """
        SELECT COUNT(DISTINCT rj.comment_id) FROM reply_jobs rj
        WHERE rj.comment_id = ANY(%(ids)s)
          AND rj.status IN ('pending','sending','sent')
    """

    COUNT_ALREADY_BY_FILTER = """
        SELECT COUNT(DISTINCT rj.comment_id)
        FROM reply_jobs rj
        JOIN comments c ON c.comment_id = rj.comment_id
        WHERE rj.status IN ('pending','sending','sent')
          AND c.topic IS NOT NULL
          AND (%(topic)s = '' OR c.topic = %(topic)s)
          AND (%(sentiment)s = '' OR c.sentiment = %(sentiment)s)
    """

    # Existing per-day load for one page (capacity is computed from the queue
    # itself — the authoritative source of truth — not a separate counter).
    PER_DAY_LOAD = """
        SELECT scheduled_for::date AS d, COUNT(*)
        FROM reply_jobs
        WHERE source_id = %(source_id)s AND status IN ('pending','sending')
        GROUP BY d
    """

    INSERT_CAMPAIGN = """
        INSERT INTO reply_campaigns
            (created_by, reply_text, filter_snapshot, total_targets, counts, status)
        VALUES
            (%(created_by)s, %(reply_text)s, %(filter_snapshot)s::jsonb,
             %(total_targets)s, %(counts)s::jsonb, 'queued')
        RETURNING id
    """

    # execute_values target. ON CONFLICT uses the partial unique index
    # uq_reply_jobs_comment_live as the race-safe no-double-reply backstop (R10).
    INSERT_JOBS = """
        INSERT INTO reply_jobs
            (campaign_id, comment_id, source_id, post_id, reply_text, scheduled_for, status)
        VALUES %s
        ON CONFLICT (comment_id) WHERE status IN ('pending','sending','sent') DO NOTHING
        RETURNING comment_id
    """

    UPDATE_CAMPAIGN_COUNTS = """
        UPDATE reply_campaigns
        SET total_targets = %(total_targets)s, counts = %(counts)s::jsonb
        WHERE id = %(id)s
    """


class QD:
    """
    Dispatcher (send-path) SQL — asyncpg positional ($n) style, used on the
    dispatcher's event loop. Kept separate from the enqueue `Q` (psycopg2 %s)
    constants to avoid mixing parameter styles.
    """

    # Pages that have due work, with the signals needed for scrape/reply
    # coordination (R5/R6): scraper status, quota backoff, latest app usage,
    # last send time (for the guaranteed drip), and the page token.
    SELECT_DUE_PAGES = """
        SELECT ss.id              AS source_id,
               ss.access_token    AS access_token,
               ss.platform        AS platform,
               MIN(rj.scheduled_for) AS oldest_due,
               COUNT(*)           AS due_count,
               COALESCE(st.status, 'IDLE') AS scraper_status,
               MAX(st.resume_at)  AS resume_at,
               COALESCE(prs.app_usage_pct, 0) AS app_usage_pct,
               (SELECT MAX(s.sent_at) FROM reply_jobs s WHERE s.source_id = ss.id) AS last_sent
        FROM reply_jobs rj
        JOIN scraping_sources ss ON ss.id = rj.source_id
        LEFT JOIN schedule_state st ON st.source_id = ss.id
        LEFT JOIN page_rate_state prs ON prs.source_id = ss.id
        WHERE rj.status = 'pending'
          AND rj.scheduled_for <= now()
          AND ss.can_reply = TRUE
        GROUP BY ss.id, ss.access_token, ss.platform, st.status, prs.app_usage_pct
        ORDER BY oldest_due ASC
    """

    # Claim a paced slice for one page (one worker per page). FOR UPDATE SKIP
    # LOCKED is the cross-process / crash-safe no-double-send primitive (R10).
    CLAIM_SLICE = """
        WITH due AS (
            SELECT id FROM reply_jobs
            WHERE source_id = $1 AND status = 'pending' AND scheduled_for <= now()
            ORDER BY id
            LIMIT $2
            FOR UPDATE SKIP LOCKED
        )
        UPDATE reply_jobs
        SET status = 'sending', claimed_at = now(), attempts = attempts + 1, updated_at = now()
        WHERE id IN (SELECT id FROM due)
        RETURNING id, comment_id, post_id, reply_text, campaign_id, attempts
    """

    MARK_SENT = """
        UPDATE reply_jobs
        SET status = 'sent', meta_reply_id = $2, sent_at = now(), updated_at = now()
        WHERE id = $1
    """

    MARK_SKIPPED = """
        UPDATE reply_jobs
        SET status = 'skipped', skip_reason = $2, updated_at = now()
        WHERE id = $1
    """

    MARK_FAILED = """
        UPDATE reply_jobs
        SET status = 'failed', error_code = $2, error_message = $3, updated_at = now()
        WHERE id = $1
    """

    REVERT_PENDING = """
        UPDATE reply_jobs
        SET status = 'pending', claimed_at = NULL, updated_at = now()
        WHERE id = ANY($1::bigint[]) AND status = 'sending'
    """

    FAIL_MANY = """
        UPDATE reply_jobs
        SET status = 'failed', error_code = $2, error_message = $3, updated_at = now()
        WHERE id = ANY($1::bigint[]) AND status IN ('sending', 'pending')
    """

    DISABLE_PAGE_REPLY = """
        UPDATE scraping_sources
        SET can_reply = FALSE, reply_perm_error = $2, reply_perm_checked_at = now()
        WHERE id = $1
    """

    RECLAIM_STALE = """
        UPDATE reply_jobs
        SET status = 'pending', claimed_at = NULL, updated_at = now()
        WHERE status = 'sending'
          AND claimed_at < now() - make_interval(secs => $1)
    """

    UPSERT_PAGE_USAGE = """
        INSERT INTO page_rate_state (source_id, app_usage_pct, observed_at)
        VALUES ($1, $2, now())
        ON CONFLICT (source_id) DO UPDATE
            SET app_usage_pct = EXCLUDED.app_usage_pct, observed_at = EXCLUDED.observed_at
    """

    # Roll each non-terminal campaign to its aggregate status (and refresh the
    # live counts) once per dispatcher tick.
    SWEEP_CAMPAIGNS = """
        WITH agg AS (
            SELECT campaign_id,
                   COUNT(*) FILTER (WHERE status IN ('pending','sending')) AS open,
                   COUNT(*) FILTER (WHERE status = 'sent')    AS sent,
                   COUNT(*) FILTER (WHERE status = 'failed')  AS failed,
                   COUNT(*) FILTER (WHERE status = 'skipped') AS skipped
            FROM reply_jobs
            GROUP BY campaign_id
        )
        UPDATE reply_campaigns c
        SET status = CASE
                        WHEN a.open > 0 THEN 'in_progress'
                        WHEN a.failed > 0 THEN 'partial'
                        ELSE 'completed'
                     END,
            completed_at = CASE WHEN a.open = 0 THEN now() ELSE NULL END,
            counts = c.counts || jsonb_build_object('sent', a.sent, 'failed', a.failed, 'skipped', a.skipped)
        FROM agg a
        WHERE a.campaign_id = c.id
          AND c.status IN ('queued', 'in_progress')
    """


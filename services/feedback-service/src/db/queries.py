"""
All SQL for feedback-service as named constants (house rule). psycopg2 named-param
style (%(name)s). Parameter-bound throughout — injection cannot reach the DB.
"""


class Q:
    # Lock the comment row for the duration of the correction TX (serializes savers).
    LOCK_COMMENT = """
        SELECT topic, sentiment, human_verified
        FROM comments
        WHERE comment_id = %(cid)s
        FOR UPDATE
    """

    # Capture the ORIGINAL (pipeline) labels — inserted BEFORE the comments overwrite (R5).
    # UNIQUE(comment_id) makes this the race-proof first-writer-wins backstop (R3).
    INSERT_FEEDBACK = """
        INSERT INTO label_feedback
            (comment_id, pipeline_topic, pipeline_sentiment, human_topic, human_sentiment,
             human_topic_key, topic_changed, sentiment_changed, user_id, batch_id)
        VALUES
            (%(comment_id)s, %(pipeline_topic)s, %(pipeline_sentiment)s, %(human_topic)s,
             %(human_sentiment)s, %(human_topic_key)s, %(topic_changed)s, %(sentiment_changed)s,
             %(user_id)s, %(batch_id)s)
    """

    UPSERT_TOPIC = """
        INSERT INTO topics (topic_key, display_label, origin, created_by)
        VALUES (%(topic_key)s, %(display_label)s, 'human', %(created_by)s)
        ON CONFLICT (topic_key) DO NOTHING
    """

    GET_TOPIC_DISPLAY = "SELECT display_label FROM topics WHERE topic_key = %(topic_key)s"

    # Overwrite the effective label with the human value + lock the row (R3).
    UPDATE_COMMENT = """
        UPDATE comments
        SET topic = %(topic)s, sentiment = %(sentiment)s,
            human_verified = true, verified_by = %(user_id)s, verified_at = now(), updated_at = now()
        WHERE comment_id = %(cid)s
    """

    # Retraining dataset (read-only, off the hot path, indexed by created_at).
    EXPORT = """
        SELECT lf.comment_id, c.text_content,
               lf.pipeline_topic, lf.pipeline_sentiment,
               lf.human_topic, lf.human_sentiment,
               lf.topic_changed, lf.sentiment_changed,
               lf.user_id, lf.created_at
        FROM label_feedback lf
        JOIN comments c ON c.comment_id = lf.comment_id
        WHERE (%(since)s IS NULL OR lf.created_at >= %(since)s)
        ORDER BY lf.created_at
        LIMIT %(limit)s
    """

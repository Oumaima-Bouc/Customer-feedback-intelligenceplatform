from __future__ import annotations
import psycopg2.extras
from config.database import get_conn
from shared.utils.date_helper import to_iso

def list_topic_names(run_date: str = ""):
    # Only topics that actually have comments in the latest (non-archived) run, so the
    # filter list stays consistent with the topic cards. Values match the comments'
    # topic column exactly, so client-side filtering works.
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT btrim(topic) FROM comments "
            "WHERE topic IS NOT NULL AND btrim(topic) <> '' AND NOT archived "
            "ORDER BY 1"
        )
        return [r[0] for r in cur.fetchall()]

def fetch_topic_comments(topic_name: str, cursor: str = "", limit: int = 10):
    with get_conn() as conn:
        # Match on the NORMALISED topic key (case/space-insensitive) so a card label that
        # differs only in casing from comments.topic still returns its comments (fixes
        # blank topic cards for pipeline-generated topics not in the registry).
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        where=["lower(btrim(topic)) = lower(btrim(%s))", "NOT archived"]; params=[topic_name]
        if cursor: where.append("comment_id > %s"); params.append(cursor)
        q = "SELECT comment_id, text_content, like_count, sentiment, created_at, source, post_id FROM comments WHERE " + " AND ".join(where) + " ORDER BY like_count DESC, comment_id LIMIT %s"
        params.append(limit + 1); cur.execute(q, params); rows = cur.fetchall()
    has_more = len(rows) > limit; rows = rows[:limit]
    return {"topic": topic_name, "comments": [{"comment_id": r["comment_id"], "text_content": r["text_content"], "like_count": r["like_count"], "sentiment": r["sentiment"], "created_at": to_iso(r["created_at"]), "source": r["source"], "post_id": r["post_id"]} for r in rows], "next_cursor": rows[-1]["comment_id"] if rows else None, "has_more": has_more}

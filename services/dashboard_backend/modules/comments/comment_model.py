from __future__ import annotations
import psycopg2.extras
from config.database import get_conn
from shared.utils.date_helper import to_iso

def _repliability(r) -> tuple[bool, str | None]:
    """Group Reply eligibility (R8/R9/R10) computed per comment for the UI.
    Mirrors reply-service's authoritative enqueue predicate."""
    if r["is_reply"]:
        return False, "Cannot reply to a reply"
    if r["post_status"] != "active":
        return False, "Post is archived or no longer tracked"
    if not r["can_reply"]:
        return False, "This page hasn't granted reply permission"
    if r["already_replied"]:
        return False, "Already replied or queued"
    return True, None


def fetch_paginated(cursor: str = "", limit: int = 50, source: str = "", sentiment: str = "", topic: str = ""):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        where=["c.topic IS NOT NULL", "NOT c.archived"]; params=[]
        if cursor: where.append("c.comment_id > %s"); params.append(cursor)
        if source: where.append("c.source = %s"); params.append(source)
        if sentiment: where.append("c.sentiment = %s"); params.append(sentiment)
        if topic: where.append("c.topic = %s"); params.append(topic)
        q = (
            "SELECT c.comment_id, c.text_content, c.source, c.scraped_at, c.sentiment, c.topic, "
            "c.cluster_id, c.like_count, c.created_at, c.is_reply, c.fallback_used, "
            "c.human_verified, c.verified_by, u.username AS verified_by_username, "
            "ap.status AS post_status, COALESCE(ss.can_reply, FALSE) AS can_reply, "
            "EXISTS (SELECT 1 FROM reply_jobs rj WHERE rj.comment_id = c.comment_id "
            "AND rj.status IN ('pending','sending','sent')) AS already_replied "
            "FROM comments c "
            "LEFT JOIN active_posts ap ON ap.post_id = c.post_id "
            "LEFT JOIN scraping_sources ss ON ss.id = ap.source_id "
            "LEFT JOIN users u ON u.id = c.verified_by "
            "WHERE " + " AND ".join(where) + " ORDER BY c.created_at DESC LIMIT %s"
        )
        params.append(limit + 1); cur.execute(q, params); rows = cur.fetchall(); has_more = len(rows) > limit; rows = rows[:limit]
        # Aggregates honour the SAME filters as the table (minus the cursor) so the
        # mentions KPI cards reflect the filtered set — or the whole run when no filter.
        agg_where = "topic IS NOT NULL AND NOT archived"; agg_params: list = []
        if source: agg_where += " AND source = %s"; agg_params.append(source)
        if sentiment: agg_where += " AND sentiment = %s"; agg_params.append(sentiment)
        if topic: agg_where += " AND topic = %s"; agg_params.append(topic)
        cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur2.execute(f"SELECT COUNT(*) FROM comments WHERE {agg_where}", agg_params); total = cur2.fetchone()["count"]
        cur2.execute(f"SELECT sentiment, COUNT(*) FROM comments WHERE {agg_where} GROUP BY sentiment", agg_params); sentiment_counts = {r["sentiment"]: r["count"] for r in cur2.fetchall()}
        cur2.execute(f"SELECT source, COUNT(*) FROM comments WHERE {agg_where} GROUP BY source", agg_params); source_rows = cur2.fetchall()
    comments = []
    for r in rows:
        repliable, blocked_reason = _repliability(r)
        comments.append({"comment_id": r["comment_id"], "text_content": r["text_content"], "source": r["source"], "scraped_at": to_iso(r["scraped_at"]), "sentiment": r["sentiment"], "topic": r["topic"], "cluster_id": r["cluster_id"], "like_count": r["like_count"], "created_at": to_iso(r["created_at"]), "is_reply": r["is_reply"], "fallback_used": r["fallback_used"], "repliable": repliable, "reply_blocked_reason": blocked_reason, "human_verified": r["human_verified"], "verified_by": r["verified_by_username"]})
    return {"total_comments": total, "sentiment": {"positive": sentiment_counts.get("positive", 0), "neutral": sentiment_counts.get("neutral", 0), "negative": sentiment_counts.get("negative", 0)}, "sources": [{"source": r["source"], "count": r["count"]} for r in source_rows], "comments": comments, "next_cursor": rows[-1]["comment_id"] if rows else None, "has_more": has_more}

def count_filtered(source: str = "", sentiment: str = "", topic: str = "") -> int:
    with get_conn() as conn:
        cur = conn.cursor(); where=["topic IS NOT NULL", "NOT archived"]; params=[]
        if source: where.append("source = %s"); params.append(source)
        if sentiment: where.append("sentiment = %s"); params.append(sentiment)
        if topic: where.append("topic = %s"); params.append(topic)
        cur.execute("SELECT COUNT(*) FROM comments WHERE " + " AND ".join(where), params); return cur.fetchone()[0]

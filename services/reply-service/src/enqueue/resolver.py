"""
Comment -> page routing & eligibility (R5, R8, R9, R10).

Resolves a selection (explicit comment_ids OR a topic/sentiment filter) to the
set of repliable targets, each carrying its resolved source_id (queue key) and
post_id — resolved ONCE here so the send path never depends on the logical
comments.post_id -> active_posts join (base spec known-debt §7.2).

All functions take a live psycopg2 cursor so they run inside the enqueue
transaction; they are pure-SQL wrappers and are unit-tested with a fake cursor.
"""
from __future__ import annotations

from typing import Optional

from db.queries import Q


def resolve_eligible(
    cur,
    *,
    use_filter: bool,
    comment_ids: Optional[list[str]],
    topic: str,
    sentiment: str,
) -> list[dict]:
    """Return repliable targets: [{comment_id, post_id, source_id}, ...]."""
    if use_filter:
        cur.execute(Q.ELIGIBLE_BY_FILTER, {"topic": topic, "sentiment": sentiment})
    else:
        cur.execute(Q.ELIGIBLE_BY_IDS, {"ids": comment_ids or []})
    return [{"comment_id": r[0], "post_id": r[1], "source_id": r[2]} for r in cur.fetchall()]


def count_requested(
    cur,
    *,
    use_filter: bool,
    comment_ids: Optional[list[str]],
    topic: str,
    sentiment: str,
) -> int:
    if use_filter:
        cur.execute(Q.COUNT_REQUESTED_BY_FILTER, {"topic": topic, "sentiment": sentiment})
    else:
        cur.execute(Q.COUNT_REQUESTED_BY_IDS, {"ids": comment_ids or []})
    return int(cur.fetchone()[0])


def count_already(
    cur,
    *,
    use_filter: bool,
    comment_ids: Optional[list[str]],
    topic: str,
    sentiment: str,
) -> int:
    if use_filter:
        cur.execute(Q.COUNT_ALREADY_BY_FILTER, {"topic": topic, "sentiment": sentiment})
    else:
        cur.execute(Q.COUNT_ALREADY_BY_IDS, {"ids": comment_ids or []})
    return int(cur.fetchone()[0])


def per_day_load(cur, source_id: int) -> dict:
    """{date: existing_pending_count} for one page."""
    cur.execute(Q.PER_DAY_LOAD, {"source_id": source_id})
    return {row[0]: int(row[1]) for row in cur.fetchall()}

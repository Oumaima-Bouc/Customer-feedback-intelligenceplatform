"""
Enqueue orchestration: selection -> repliable targets -> per-page capacity
schedule -> transactional insert of campaign + jobs -> immediate ack (R1).

NOTHING is sent here. The dispatcher (send-path pass) drains the queues later.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from psycopg2.extras import execute_values

from config import settings
from db.connection import get_conn
from db.queries import Q
from enqueue import resolver
from enqueue.scheduler import assign_schedule, window_start

logger = logging.getLogger(__name__)


def create_campaign(
    *,
    reply_text: str,
    comment_ids: Optional[list[str]] = None,
    filter: Optional[dict] = None,  # noqa: A002 — matches the API field name
    select_all_matching: bool = False,
    created_by: Optional[int] = None,
) -> dict:
    """
    Resolve + schedule + persist one Group Reply campaign. Returns the user ack.

    `select_all_matching=true` (or no explicit ids) re-resolves the set from the
    filter authoritatively (R3) — the caller never has to ship every id.
    """
    flt = filter or {}
    topic = (flt.get("topic") or "").strip()
    sentiment = (flt.get("sentiment") or "").strip()
    use_filter = bool(select_all_matching) or not comment_ids
    now = datetime.now(timezone.utc)

    with get_conn() as conn:
        cur = conn.cursor()

        eligible = resolver.resolve_eligible(
            cur, use_filter=use_filter, comment_ids=comment_ids, topic=topic, sentiment=sentiment
        )
        requested = resolver.count_requested(
            cur, use_filter=use_filter, comment_ids=comment_ids, topic=topic, sentiment=sentiment
        )
        already = resolver.count_already(
            cur, use_filter=use_filter, comment_ids=comment_ids, topic=topic, sentiment=sentiment
        )

        # Per-page capacity scheduling (R7).
        by_page: dict[int, list[dict]] = defaultdict(list)
        for e in eligible:
            by_page[e["source_id"]].append(e)

        job_rows: list[tuple] = []
        furthest = now.date()
        for source_id, items in by_page.items():
            per_day = resolver.per_day_load(cur, source_id)
            sched, page_furthest = assign_schedule(
                now, per_day,
                settings.capacity_daily_per_page, len(items),
                settings.capacity_max_backlog_days, settings.window_hours,
            )
            if page_furthest > furthest:
                furthest = page_furthest
            for e, when in zip(items, sched):
                # campaign_id is filled after the campaign insert
                job_rows.append((e["comment_id"], source_id, e["post_id"], reply_text, when))

        counts = {"accepted": 0, "skipped_not_repliable": 0, "skipped_already": already, "sent": 0, "failed": 0}
        filter_snapshot = {"topic": topic, "sentiment": sentiment, "select_all_matching": bool(select_all_matching)}

        cur.execute(
            Q.INSERT_CAMPAIGN,
            {
                "created_by": created_by,
                "reply_text": reply_text,
                "filter_snapshot": json.dumps(filter_snapshot),
                "total_targets": len(eligible),
                "counts": json.dumps(counts),
            },
        )
        campaign_id = cur.fetchone()[0]

        accepted = 0
        if job_rows:
            rows = [(campaign_id, cid, sid, pid, txt, when, "pending") for (cid, sid, pid, txt, when) in job_rows]
            inserted = execute_values(
                cur, Q.INSERT_JOBS, rows,
                template="(%s,%s,%s,%s,%s,%s,%s)", fetch=True,
            )
            accepted = len(inserted)

        skipped_not_repliable = max(requested - accepted - already, 0)
        counts.update({"accepted": accepted, "skipped_not_repliable": skipped_not_repliable})
        cur.execute(
            Q.UPDATE_CAMPAIGN_COUNTS,
            {"total_targets": accepted, "counts": json.dumps(counts), "id": campaign_id},
        )

    eta = _eta(now, furthest, settings.window_hours)
    message = "Replies will be sent within the next 24 hours."
    if furthest > now.date():
        message = (
            f"Most replies will be sent within the next 24 hours; about {accepted} are "
            f"scheduled through {furthest.isoformat()} due to existing volume on some pages."
        )

    logger.info(
        "reply.enqueued",
        extra={
            "campaign_id": campaign_id, "accepted": accepted,
            "skipped_not_repliable": skipped_not_repliable, "skipped_already": already,
            "pages": len(by_page), "eta": eta,
        },
    )
    return {
        "campaign_id": campaign_id,
        "accepted": accepted,
        "skipped": {"not_repliable": skipped_not_repliable, "already_queued": already},
        "eta": eta,
        "message": message,
    }


def _eta(now: datetime, furthest, window_hours: int) -> str:
    """ISO timestamp by which the last reply is expected to be sent."""
    if furthest <= now.date():
        return (now + timedelta(hours=window_hours)).isoformat()
    return (window_start(furthest) + timedelta(hours=window_hours)).isoformat()

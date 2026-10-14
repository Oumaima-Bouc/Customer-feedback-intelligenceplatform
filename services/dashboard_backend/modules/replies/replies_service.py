from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

import psycopg2.extras

from config.database import get_conn
from middleware.error_middleware import NotFoundError, ValidationError
from shared.utils.date_helper import to_iso

# reply-service control endpoint on the internal docker network.
_REPLY_BASE_URL = os.environ.get("REPLY_SERVICE_URL", "http://reply-service:8083")
_INTERNAL_SECRET = os.environ.get("REPLY_INTERNAL_SECRET", "")


def _call_reply_service(path: str, payload: dict, timeout: int = 30) -> dict:
    """POST to reply-service. Surfaces a clear ValidationError on 4xx / unreachable."""
    url = f"{_REPLY_BASE_URL}{path}"
    data = json.dumps(payload or {}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if _INTERNAL_SECRET:
        headers["X-Internal-Secret"] = _INTERNAL_SECRET
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        try:
            parsed = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            parsed = {}
        raise ValidationError(parsed.get("detail") or parsed.get("error") or f"Reply service error {exc.code}")
    except Exception as exc:  # URLError / timeout / connection refused
        raise ValidationError(f"Reply service is unavailable: {exc}")


def submit_campaign(
    reply_text: str,
    comment_ids: Optional[list[str]],
    filter: Optional[dict],  # noqa: A002 — matches API field
    select_all_matching: bool,
    created_by: int,
) -> dict:
    if not reply_text or not reply_text.strip():
        raise ValidationError("reply_text is required")
    return _call_reply_service(
        "/internal/replies",
        {
            "reply_text": reply_text,
            "comment_ids": comment_ids,
            "filter": filter,
            "select_all_matching": select_all_matching,
            "created_by": created_by,
        },
    )


def list_campaigns(limit: int = 50) -> dict:
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, created_by, reply_text, total_targets, counts, status, created_at, completed_at "
            "FROM reply_campaigns ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    return {
        "total": len(rows),
        "campaigns": [
            {
                "id": r["id"],
                "reply_text": r["reply_text"],
                "total_targets": r["total_targets"],
                "counts": r["counts"] or {},
                "status": r["status"],
                "created_at": to_iso(r["created_at"]),
                "completed_at": to_iso(r["completed_at"]),
            }
            for r in rows
        ],
    }


def get_campaign(campaign_id: int) -> dict:
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, created_by, reply_text, filter_snapshot, total_targets, counts, status, created_at, completed_at "
            "FROM reply_campaigns WHERE id = %s",
            (campaign_id,),
        )
        c = cur.fetchone()
        if not c:
            raise NotFoundError("Campaign not found")
        cur.execute(
            """
            SELECT ss.id AS source_id, ss.name, ss.platform,
                   COUNT(*) FILTER (WHERE rj.status = 'sent')    AS sent,
                   COUNT(*) FILTER (WHERE rj.status = 'pending') AS pending,
                   COUNT(*) FILTER (WHERE rj.status = 'sending') AS sending,
                   COUNT(*) FILTER (WHERE rj.status = 'skipped') AS skipped,
                   COUNT(*) FILTER (WHERE rj.status = 'failed')  AS failed,
                   MAX(rj.scheduled_for) AS last_scheduled_for
            FROM reply_jobs rj
            JOIN scraping_sources ss ON ss.id = rj.source_id
            WHERE rj.campaign_id = %s
            GROUP BY ss.id, ss.name, ss.platform
            ORDER BY ss.id
            """,
            (campaign_id,),
        )
        pages = cur.fetchall()
    return {
        "id": c["id"],
        "reply_text": c["reply_text"],
        "filter_snapshot": c["filter_snapshot"] or {},
        "total_targets": c["total_targets"],
        "counts": c["counts"] or {},
        "status": c["status"],
        "created_at": to_iso(c["created_at"]),
        "completed_at": to_iso(c["completed_at"]),
        "pages": [
            {
                "source_id": p["source_id"],
                "name": p["name"],
                "platform": p["platform"],
                "sent": p["sent"],
                "pending": p["pending"],
                "sending": p["sending"],
                "skipped": p["skipped"],
                "failed": p["failed"],
                "last_scheduled_for": to_iso(p["last_scheduled_for"]),
            }
            for p in pages
        ],
    }

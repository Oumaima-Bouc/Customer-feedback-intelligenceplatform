"""
C4 - Data Processing & Persistence
modules/persistence.py
Phase 4: Persistence Layer.
- Idempotent UPSERT of all staged comment dicts into PostgreSQL.
- Per-comment error isolation: one bad row never aborts the batch.
- CSV export + row deletion lifecycle for the sentiment pipeline handoff.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

import structlog

from db.connection import get_pool
from db.queries import Queries

log = structlog.get_logger(__name__)


async def run_persistence(comments: list[dict[str, Any]]) -> int:
    """
    Phase 4 - Persist staged comments to PostgreSQL.
    Each comment is UPSERTed individually.
    A failure on one row is logged and skipped - the batch continues.

    Args:
        comments: List of normalized comment dicts from C3.

    Returns:
        Count of successfully upserted comments.
    """
    if not comments:
        log.info("persistence.no_comments")
        return 0

    log.info("persistence.start", total=len(comments))
    pool = await get_pool()
    success = 0
    failed = 0

    async with pool.acquire() as conn:
        for comment in comments:
            try:
                await conn.execute(
                    Queries.UPSERT_COMMENT,
                    comment["comment_id"],
                    comment["post_id"],
                    comment["text_content"],
                    comment["like_count"],
                    comment["created_at"],
                    comment["is_reply"],
                    comment["source"],
                )
                success += 1
            except Exception as exc:
                failed += 1
                log.error(
                    "persistence.upsert_failed",
                    comment_id=comment.get("comment_id", "unknown"),
                    error=str(exc),
                )

    log.info(
        "persistence.complete",
        success=success,
        failed=failed,
        total=len(comments),
    )
    return success


async def export_and_clear_processed() -> str:
    """
    Exports all comments where processed_for_sentiment=FALSE to a CSV string,
    then marks them as processed=TRUE, then deletes them from the DB.

    Returns:
        CSV content as a string.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(Queries.GET_UNPROCESSED_COMMENTS)

    if not rows:
        log.info("persistence.export.no_rows")
        return ""

    log.info("persistence.export.start", row_count=len(rows))

    # -- Build CSV in memory --
    output = io.StringIO()
    fieldnames = [
        "comment_id", "post_id", "text_content", "like_count",
        "created_at", "is_reply", "scraped_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
    writer.writeheader()

    exported_ids: list[str] = []
    for row in rows:
        writer.writerow({
            "comment_id":   row["comment_id"],
            "post_id":      row["post_id"],
            "text_content": row["text_content"],
            "like_count":   row["like_count"],
            "created_at":   row["created_at"].isoformat() if row["created_at"] else "",
            "is_reply":     row["is_reply"],
            "scraped_at":   row["scraped_at"].isoformat() if row["scraped_at"] else "",
        })
        exported_ids.append(row["comment_id"])

    csv_content = output.getvalue()

    # -- Only delete AFTER CSV is confirmed in memory --
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(Queries.MARK_COMMENTS_PROCESSED, exported_ids)
            await conn.execute(Queries.DELETE_PROCESSED_COMMENTS, exported_ids)

    log.info(
        "persistence.export.complete",
        exported=len(exported_ids),
    )
    return csv_content

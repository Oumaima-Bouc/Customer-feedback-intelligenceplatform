"""
C3 - Scraper Engine
modules/comment_engine.py
Phase 2: Comment Ingestion Engine.
- Differential sync: only fetches comments newer than last_scraped_at per post.
- Recursive cursor-based pagination.
- asyncio.Semaphore(SEMAPHORE_LIMIT) bounds concurrent post workers.
- Filters out replies when SCRAPE_REPLIES=false.
- Saves cursor after each page (crash-safe).
- On cursor expiry: falls back to last_success_at via RecoveryManager.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

import structlog

from config import settings
from db.connection import get_pool
from db.queries import Queries
from modules.rate_guard import (
    APIQuotaWarning,
    APIRateLimitException,
    CursorExpiredException,
)
from api.graph_client import PostNotFoundError, PermissionError, GraphClientError

if TYPE_CHECKING:
    from api.graph_client import GraphClient
    from modules.recovery import RecoveryManager

log = structlog.get_logger(__name__)

# Output schema - all keys required
COMMENT_SCHEMA_KEYS = {"comment_id", "post_id", "text_content", "like_count", "created_at", "is_reply", "source"}


async def run_comment_ingestion(
    client: "GraphClient",
    recovery: "RecoveryManager",
    post_ids: list[str],
    source: str,
    resume_state: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    Phase 2 - Comment Ingestion Engine.
    Fetches new comments for each active post in parallel (bounded by semaphore).

    Args:
        client:       GraphClient with C5 middleware injected.
        recovery:     RecoveryManager for cursor expiry handling.
        post_ids:     List of active post_ids from Phase 1.
        resume_state: {'post_id': str, 'cursor': str} from C2 on resume, or None.

    Returns:
        Flat list of normalized comment dicts (schema: COMMENT_SCHEMA_KEYS).

    Raises:
        APIQuotaWarning:       propagated up to C2 for recovery handling.
        APIRateLimitException: propagated up to C2 for recovery handling.
    """
    semaphore = asyncio.Semaphore(settings.semaphore_limit)
    all_comments: list[dict[str, Any]] = []
    results_lock = asyncio.Lock()

    # Determine if we're resuming a paused run for a specific post.
    resume_post_id: Optional[str] = None
    resume_cursor: Optional[str] = None
    if resume_state:
        resume_post_id = resume_state.get("post_id")
        resume_cursor = resume_state.get("cursor")
        log.info(
            "comment_engine.resuming",
            post_id=resume_post_id,
            cursor_prefix=resume_cursor[:20] if resume_cursor else None,
        )

    async def process_post(post_id: str) -> None:
        async with semaphore:
            inject_cursor = resume_cursor if post_id == resume_post_id else None
            comments = await _scrape_post_comments(
                client=client,
                recovery=recovery,
                post_id=post_id,
                source=source,
                start_cursor=inject_cursor,
            )
            async with results_lock:
                all_comments.extend(comments)

    # -- Launch concurrent workers --
    tasks = [asyncio.create_task(process_post(pid)) for pid in post_ids]
    try:
        await asyncio.gather(*tasks)
    except (APIQuotaWarning, APIRateLimitException):
        # Cancel remaining tasks cleanly before propagating to C2.
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    log.info(
        "comment_engine.complete",
        posts_processed=len(post_ids),
        total_comments=len(all_comments),
    )
    return all_comments


async def _scrape_post_comments(
    client: "GraphClient",
    recovery: "RecoveryManager",
    post_id: str,
    source: str,
    start_cursor: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Fetches all new comments for a single post.
    Follows pagination until exhausted.
    Saves cursor to DB after each page (crash-safe intermediate state).
    """
    # Determine the watermark for this post.
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_scraped_at, last_comment_cursor FROM active_posts WHERE post_id = $1",
            post_id,
        )

    last_scraped_at: Optional[datetime] = row["last_scraped_at"] if row else None

    params: dict[str, Any] = {
        "fields": "id,message,created_time,parent_id",
        "limit": 100,
    }
    if start_cursor:
        params["after"] = start_cursor
    elif last_scraped_at:
        params["since"] = int(last_scraped_at.timestamp())

    comments: list[dict[str, Any]] = []
    page_num = 0

    while True:
        page_num += 1
        try:
            data = await client.get(f"/{post_id}/comments", params)
        except CursorExpiredException:
            # Fallback: drop cursor, restart from last_success_at.
            fallback_ts = await recovery.handle_cursor_expiry(post_id, last_scraped_at)
            params = {"fields": "id,message,created_time,parent_id", "limit": 100}
            if fallback_ts:
                params["since"] = int(fallback_ts.timestamp())
            data = await client.get(f"/{post_id}/comments", params)
        except PostNotFoundError:
            log.warning("comment_engine.post_not_found", post_id=post_id)
            return []
        except PermissionError:
            log.warning("comment_engine.permission_denied", post_id=post_id)
            return []
        except GraphClientError as exc:
            log.error("comment_engine.api_error", post_id=post_id, code=exc.code, msg=exc.message)
            return []

        raw_comments: list[dict] = data.get("data", [])
        page_comments = _normalize_comments(raw_comments, post_id, source)
        comments.extend(page_comments)

        # Save cursor after each page - crash-safe resume.
        paging = data.get("paging", {})
        cursor_after: Optional[str] = paging.get("cursors", {}).get("after")
        if cursor_after:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(Queries.UPDATE_POST_CURSOR, post_id, cursor_after)

        log.debug(
            "comment_engine.page",
            post_id=post_id,
            page=page_num,
            comments_this_page=len(page_comments),
            total=len(comments),
        )

        if not paging.get("next") or not cursor_after:
            break

        params = {
            "fields": "id,message,created_time,parent_id",
            "limit": 100,
            "after": cursor_after,
        }

    log.info(
        "comment_engine.post_done",
        post_id=post_id,
        total_comments=len(comments),
        pages=page_num,
    )
    return comments


def _normalize_comments(
    raw: list[dict[str, Any]],
    post_id: str,
    source: str,
) -> list[dict[str, Any]]:
    """
    Normalizes raw Meta API comment objects into the output contract schema.
    Filters out replies if SCRAPE_REPLIES=false.
    """
    result: list[dict[str, Any]] = []

    for raw_c in raw:
        try:
            parent_id: Optional[str] = raw_c.get("parent_id")
            is_reply: bool = parent_id is not None

            if is_reply and not settings.scrape_replies:
                continue

            comment: dict[str, Any] = {
                "comment_id": raw_c["id"],
                "post_id": post_id,
                "text_content": raw_c.get("message", ""),
                "like_count": 0,
                "created_at": _parse_fb_datetime(raw_c["created_time"]),
                "is_reply": is_reply,
                "source": source,
            }

            assert set(comment.keys()) == COMMENT_SCHEMA_KEYS
            result.append(comment)
        except (KeyError, AssertionError, ValueError) as exc:
            log.warning(
                "comment_engine.normalize_skip",
                raw_id=raw_c.get("id", "unknown"),
                error=str(exc),
            )

    return result


def _parse_fb_datetime(value: str) -> datetime:
    value = value.replace("+0000", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

"""
C3 - Scraper Engine
modules/discovery.py
Phase 1: Discovery Engine.
Fetches all posts published in the last MAX_POST_AGE_H window.
UPSERTs results into active_posts. Archives posts that are now too old.
Returns a list of active post_ids for Phase 2.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog

from config import settings
from db.connection import get_pool
from db.queries import Queries

if TYPE_CHECKING:
    from api.graph_client import GraphClient

log = structlog.get_logger(__name__)


async def run_discovery(client: "GraphClient", external_id: str, source_id: int) -> list[str]:
    """
    Phase 1 - Discovery Engine.
    Calls GET /{PAGE_ID}/feed?fields=id,created_time&since={window_start}
    Paginates through all results.
    UPSERTs each post into active_posts.
    Archives posts older than MAX_POST_AGE_H.

    Args:
        client: Authenticated GraphClient instance (C3).

    Returns:
        List of active post_id strings (up to MAX_ACTIVE_POSTS).
    """
    window_start = datetime.now(tz=timezone.utc) - timedelta(hours=settings.max_post_age_h)
    since_unix = int(window_start.timestamp())

    log.info(
        "discovery.start",
        page_id=external_id,
        window_hours=settings.max_post_age_h,
        since=window_start.isoformat(),
    )

    post_ids: list[str] = []
    params: dict = {
        "fields": "id,created_time",
        "since": since_unix,
        "limit": 100,
    }
    path = f"/{external_id}/feed"

    # -- Pagination loop --
    page_num = 0
    while True:
        page_num += 1
        data = await client.get(path, params)
        page_posts = data.get("data", [])

        if not page_posts:
            break

        pool = await get_pool()
        async with pool.acquire() as conn:
            for post in page_posts:
                post_id: str = post["id"]
                created_time: datetime = _parse_fb_datetime(post["created_time"])
                await conn.execute(Queries.UPSERT_POST, post_id, created_time, source_id)
                post_ids.append(post_id)

        log.debug(
            "discovery.page_fetched",
            page=page_num,
            posts_this_page=len(page_posts),
            total_so_far=len(post_ids),
        )

        # Follow pagination cursor
        paging = data.get("paging", {})
        next_cursor = paging.get("cursors", {}).get("after")
        if not paging.get("next") or not next_cursor:
            break
        params = {
            "fields": "id,created_time",
            "limit": 100,
            "after": next_cursor,
        }
        path = f"/{external_id}/feed"

    # -- Archive posts that aged out --
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(Queries.ARCHIVE_OLD_POSTS, str(settings.max_post_age_h))

    # -- Fetch current active list (respects MAX_ACTIVE_POSTS) --
    async with pool.acquire() as conn:
        rows = await conn.fetch(Queries.GET_ACTIVE_POSTS, settings.max_active_posts, source_id)

    active_ids = [row["post_id"] for row in rows]
    log.info(
        "discovery.complete",
        total_discovered=len(post_ids),
        active_posts=len(active_ids),
    )
    return active_ids


def _parse_fb_datetime(value: str) -> datetime:
    """
    Parses Meta's ISO 8601 datetime string into a timezone-aware datetime.
    Meta returns strings like: '2024-01-15T14:30:00+0000'
    """
    value = value.replace("+0000", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

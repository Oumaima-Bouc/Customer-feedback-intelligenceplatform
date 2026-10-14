"""
C4 - Data Processing & Persistence
modules/validity_checker.py
Pre-flight check before each cycle.
Verifies that every post in active_posts still exists on Meta.
Marks deleted/invalid posts so they are excluded from scraping.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from db.connection import get_pool
from db.queries import Queries
from config import settings
from api.graph_client import PostNotFoundError, GraphClientError

if TYPE_CHECKING:
    from api.graph_client import GraphClient

log = structlog.get_logger(__name__)


async def run_post_validity_check(client: "GraphClient", source_id: int | None = None) -> list[str]:
    """
    Checks each active post against the Meta API.
    Sets status='invalid' for posts that no longer exist.

    Args:
        client: Authenticated GraphClient (C3).

    Returns:
        List of post_ids that are confirmed valid and active.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(Queries.GET_ACTIVE_POSTS, settings.max_active_posts, source_id)

    if not rows:
        log.info("validity_checker.no_active_posts")
        return []

    log.info("validity_checker.start", total_posts=len(rows))

    valid_ids: list[str] = []
    invalid_count = 0

    for row in rows:
        post_id: str = row["post_id"]
        try:
            await client.get(f"/{post_id}", {"fields": "id"})
            valid_ids.append(post_id)
        except PostNotFoundError:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(Queries.MARK_POST_INVALID, post_id)
            invalid_count += 1
            log.warning("validity_checker.post_invalid", post_id=post_id)
        except GraphClientError as exc:
            log.error(
                "validity_checker.api_error",
                post_id=post_id,
                code=exc.code,
                msg=exc.message,
            )

    log.info(
        "validity_checker.complete",
        valid=len(valid_ids),
        invalid=invalid_count,
    )
    return valid_ids

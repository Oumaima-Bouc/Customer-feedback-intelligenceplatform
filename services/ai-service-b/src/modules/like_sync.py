"""
C4 - Data Processing & Persistence
modules/like_sync.py
Phase 3: Like-Weight Sync.
Batch-refreshes like_count for all comments on active posts.
Sends up to BATCH_LIKE_SIZE (50) comment IDs per Graph API call.
Skips entirely if C5's rate_guard reports quota > 90%.
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

import structlog

from config import settings
from db.connection import get_pool
from db.queries import Queries
from api.graph_client import GraphClientError

if TYPE_CHECKING:
    from api.graph_client import GraphClient
    from modules.rate_guard import RateGuard

log = structlog.get_logger(__name__)


async def run_like_sync(
    client: "GraphClient",
    rate_guard: "RateGuard",
    post_ids: list[str],
) -> None:
    """
    Phase 3 - Like-Weight Sync.

    Args:
        client:     GraphClient for API calls.
        rate_guard: C5 RateGuard instance - checked for skip-threshold.
        post_ids:   List of active post_ids whose comments need refreshing.
    """
    # -- Priority guard: skip like sync if quota is too high --
    if rate_guard.should_skip_like_sync:
        log.warning(
            "like_sync.skipped_quota",
            quota_pct=f"{rate_guard.quota_pct:.1%}",
            threshold=f"{settings.like_skip_threshold:.1%}",
        )
        return

    # -- Fetch comment IDs for active posts --
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            Queries.GET_COMMENT_IDS_FOR_LIKE_SYNC,
            post_ids,
            10_000,
        )

    if not rows:
        log.info("like_sync.no_comments")
        return

    comment_ids = [row["comment_id"] for row in rows]
    total = len(comment_ids)
    log.info("like_sync.start", total_comments=total, batch_size=settings.batch_like_size)

    # -- Batch into chunks of BATCH_LIKE_SIZE --
    chunks = _chunk(comment_ids, settings.batch_like_size)
    updated = 0
    skipped = 0

    for i, chunk in enumerate(chunks):
        if rate_guard.should_skip_like_sync:
            log.warning(
                "like_sync.abort_mid_batch",
                quota_pct=f"{rate_guard.quota_pct:.1%}",
                batches_done=i,
                remaining_batches=len(chunks) - i,
            )
            break

        try:
            data = await client.get(
                "",
                {
                    "ids": ",".join(chunk),
                    "fields": "id,like_count",
                },
            )
        except GraphClientError as exc:
            log.error(
                "like_sync.batch_error",
                batch=i,
                code=exc.code,
                msg=exc.message,
            )
            skipped += len(chunk)
            continue

        # -- Apply updates --
        pool = await get_pool()
        async with pool.acquire() as conn:
            for comment_id, comment_data in data.items():
                if not isinstance(comment_data, dict):
                    continue
                like_count: int = comment_data.get("like_count", 0)
                await conn.execute(Queries.UPDATE_LIKE_COUNT, comment_id, like_count)
                updated += 1

        log.debug("like_sync.batch_done", batch=i + 1, updated=updated)

    log.info(
        "like_sync.complete",
        total=total,
        updated=updated,
        skipped=skipped,
    )


def _chunk(lst: list[Any], size: int) -> list[list[Any]]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]

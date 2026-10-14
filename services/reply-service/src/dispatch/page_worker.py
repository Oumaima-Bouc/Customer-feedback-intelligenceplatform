"""
Per-page worker: claim a paced slice -> send -> record (R9, R10, isolation).

One worker drains one page per tick. The claim uses FOR UPDATE SKIP LOCKED so a
crash or a (future) second replica can never double-send the same job. Per-comment
outcomes are isolated; a page that loses permission or hits its quota ceiling stops
without affecting any other page.
"""
from __future__ import annotations

import asyncio
import os

import structlog

from db.queries import QD
from shared.meta_graph import (
    APIQuotaWarning,
    APIRateLimitException,
    GraphClient,
    GraphClientError,
    PermissionError,  # noqa: A004
    PostNotFoundError,
    RateGuard,
    TokenExpiredError,
)

log = structlog.get_logger(__name__)


async def _exec(pool, sql, *args) -> None:
    async with pool.acquire() as conn:
        await conn.execute(sql, *args)


async def drain_page(pool, page: dict, settings) -> None:
    source_id = page["source_id"]
    token = page.get("access_token") or os.environ.get("META_ACCESS_TOKEN", "")
    if not token:
        log.warning("reply.no_token", source_id=source_id)
        return

    ceiling_fraction = float(settings.reply_usage_ceiling) / 100.0
    guard = RateGuard(rate_limit_threshold=ceiling_fraction, like_skip_threshold=1.0)

    # ── Claim a slice (atomic; commits the 'sending' transition) ──
    async with pool.acquire() as conn:
        async with conn.transaction():
            claimed = await conn.fetch(QD.CLAIM_SLICE, source_id, int(page["max_sends"]))
    if not claimed:
        return

    pace = 60.0 / max(int(settings.reply_max_per_minute), 1)
    log.info("reply.page_drain_start", source_id=source_id, claimed=len(claimed), mode=page.get("mode"))

    async with GraphClient(
        base_url=settings.graph_base_url,
        access_token=token,
        rate_guard=guard,
        max_attempts=settings.send_max_attempts,
    ) as client:
        for i, job in enumerate(claimed):
            jid = job["id"]
            try:
                reply_id = await client.post_reply(job["comment_id"], job["reply_text"])
            except (APIRateLimitException, APIQuotaWarning) as exc:
                # 429 / quota — request was rejected (nothing created). Leave this
                # job + the rest pending; they retry on a later eligible tick (R6/R7).
                remaining = [j["id"] for j in claimed[i:]]
                await _exec(pool, QD.REVERT_PENDING, remaining)
                log.warning("reply.page_backoff", source_id=source_id, reason=str(exc), reverted=len(remaining))
                break
            except (PermissionError, TokenExpiredError) as exc:
                # Token/permission lost mid-drain — isolate the page: fail this job
                # + the rest (terminal, so campaigns can complete) and disable replies.
                remaining = [j["id"] for j in claimed[i:]]
                await _exec(pool, QD.FAIL_MANY, remaining, "permission", str(exc)[:500])
                await _exec(pool, QD.DISABLE_PAGE_REPLY, source_id, str(exc)[:500])
                log.error("reply.page_permission_lost", source_id=source_id, failed=len(remaining))
                break
            except PostNotFoundError:
                await _exec(pool, QD.MARK_SKIPPED, jid, "comment or post deleted")  # R9
            except GraphClientError as exc:
                if int(job["attempts"]) >= int(settings.send_max_attempts):
                    await _exec(pool, QD.MARK_FAILED, jid, "send_error", str(exc)[:500])
                else:
                    await _exec(pool, QD.REVERT_PENDING, [jid])  # transient — retry later
            else:
                await _exec(pool, QD.MARK_SENT, jid, reply_id)

            # Publish the latest usage (0-100) and stop the page if it crossed the ceiling.
            try:
                await _exec(pool, QD.UPSERT_PAGE_USAGE, source_id, round(guard.quota_pct * 100, 2))
            except Exception:  # noqa: BLE001 — page_rate_state is best-effort
                pass
            if guard.quota_pct >= ceiling_fraction:
                remaining = [j["id"] for j in claimed[i + 1:]]
                if remaining:
                    await _exec(pool, QD.REVERT_PENDING, remaining)
                log.info("reply.page_ceiling_reached", source_id=source_id, quota_pct=round(guard.quota_pct, 3))
                break

            if i < len(claimed) - 1:
                await asyncio.sleep(pace)

    log.info("reply.page_drain_done", source_id=source_id)

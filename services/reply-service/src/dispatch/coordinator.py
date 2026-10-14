"""
Dispatcher coordinator: the tick loop that drives the send path.

Each tick:
  1. reclaim stale claims (crash recovery)
  2. select eligible pages (scrape/reply coordination)
  3. drain them concurrently, bounded by worker_pool_size, ONE worker per page
  4. roll campaign statuses

Pages are drained concurrently within a tick, so a slow/paused page never blocks
another (R4). With a single reply-service node, selecting each page once per tick
+ awaiting the batch guarantees one worker per page; the FOR UPDATE SKIP LOCKED
claim is the additional crash/replica-safety primitive.
"""
from __future__ import annotations

import asyncio

import structlog

from config import settings
from db.connection import close_pool, get_pool
from db.queries import QD
from dispatch import page_selector, page_worker
from modules import heartbeat

log = structlog.get_logger(__name__)


async def _sweep_campaigns(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(QD.SWEEP_CAMPAIGNS)


async def dispatch_once(pool) -> None:
    await heartbeat.reclaim_stale(pool, settings.send_claim_timeout_seconds)

    pages = await page_selector.select_due_pages(pool, settings)
    if pages:
        sem = asyncio.Semaphore(max(int(settings.worker_pool_size), 1))

        async def _run(p: dict) -> None:
            async with sem:
                try:
                    await page_worker.drain_page(pool, p, settings)
                except Exception as exc:  # noqa: BLE001 — one page's failure must not abort the tick
                    log.error("reply.drain_failed", source_id=p.get("source_id"), error=str(exc), exc_info=True)

        await asyncio.gather(*[_run(p) for p in pages])

    try:
        await _sweep_campaigns(pool)
    except Exception as exc:  # noqa: BLE001
        log.error("reply.campaign_sweep_failed", error=str(exc))


async def run_dispatcher(shutdown: asyncio.Event) -> None:
    """Tick until shutdown; tick cadence (dispatch.tick_seconds) is read live."""
    pool = await get_pool()
    log.info("dispatcher.started", tick_seconds=settings.dispatch_tick_seconds)
    try:
        while not shutdown.is_set():
            try:
                await dispatch_once(pool)
            except Exception as exc:  # noqa: BLE001
                log.error("dispatch_once_failed", error=str(exc), exc_info=True)
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=max(int(settings.dispatch_tick_seconds), 1))
            except asyncio.TimeoutError:
                pass
    finally:
        await close_pool()
        log.info("dispatcher.stopped")

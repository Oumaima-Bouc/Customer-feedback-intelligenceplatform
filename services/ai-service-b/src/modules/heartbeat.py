"""
C2 - Scheduler & Orchestrator
modules/heartbeat.py
Background asyncio Task that updates heartbeat_at every 60 seconds.
If the process dies (OOM, SIGKILL) before cancellation,
the scheduler detects a stale heartbeat on the next trigger and resets the lock.
"""
from __future__ import annotations

import asyncio

import structlog

from db.connection import get_pool
from db.queries import Queries

log = structlog.get_logger(__name__)

HEARTBEAT_INTERVAL_S = 60


async def run_heartbeat(job_id: str) -> None:
    """
    Infinite loop that updates heartbeat_at every HEARTBEAT_INTERVAL_S for a specific job.
    Must be run as an asyncio Task and cancelled when the job completes.
    """
    log.debug("heartbeat.started", job_id=job_id)
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            try:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(Queries.UPDATE_HEARTBEAT, job_id)
                log.debug("heartbeat.beat", job_id=job_id)
            except Exception as exc:
                log.warning("heartbeat.update_failed", job_id=job_id, error=str(exc))
    except asyncio.CancelledError:
        log.debug("heartbeat.cancelled", job_id=job_id)

"""
C2 - Scheduler & Orchestrator
modules/lock_manager.py
Atomic distributed lock using PostgreSQL FOR UPDATE SKIP LOCKED.
Manages all schedule_state status transitions.
Implements zombie worker detection (stale heartbeat > 5 minutes).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Any

import asyncpg
import structlog

from db.connection import get_pool
from db.queries import Queries

log = structlog.get_logger(__name__)

class LockNotAcquiredError(Exception):
    """Another instance is already running - current trigger should exit."""


class LockManager:
    """
    Manages a single job row in schedule_state, keyed by job_id.
    One LockManager instance per source job.

    Usage pattern (in orchestrator):
        async with LockManager(job_id="facebook_scraper_xxx") as lm:
            resume_state = lm.resume_state
            # ... run pipeline phases ...
        # lock auto-released on exit
    """

    def __init__(self, job_id: str, source_id: int | None = None, platform: str | None = None) -> None:
        self._job_id = job_id
        self._source_id = source_id
        self._platform = platform
        self._conn: Optional[asyncpg.Connection] = None
        self._pool = None
        self.resume_state: Optional[dict[str, Any]] = None

    async def __aenter__(self) -> "LockManager":
        await self._ensure_job_row()
        # -- Step 1: Zombie detection --
        await self._reset_zombie_if_stale()

        # -- Step 2: Acquire lock --
        self._pool = await get_pool()
        self._conn = await self._pool.acquire()

        try:
            row = await self._conn.fetchrow(Queries.LOCK_JOB, self._job_id)
        except Exception:
            await self._pool.release(self._conn)
            self._conn = None
            raise

        if row is None:
            await self._pool.release(self._conn)
            self._conn = None
            log.info("lock_manager.already_running", job_id=self._job_id)
            raise LockNotAcquiredError(f"Job {self._job_id} is already running in another instance")

        # -- Step 3: Check if this is a resume from PAUSED state --
        status: str = row["status"]
        if status == "PAUSED":
            self.resume_state = {
                "post_id": row["current_post_id"],
                "cursor": row["last_cursor"],
            }
            log.info(
                "lock_manager.resuming_paused",
                job_id=self._job_id,
                post_id=self.resume_state["post_id"],
                resume_at=row["resume_at"],
            )
        elif status in ("IDLE", "FAILED"):
            # FAILED is recoverable, not a dead-end: a previously crashed run must never
            # permanently block future runs. Acquire and start fresh. (Stale RUNNING
            # zombies are already reset to IDLE in _reset_zombie_if_stale.)
            self.resume_state = None
            if status == "FAILED":
                log.info("lock_manager.recovering_from_failed", job_id=self._job_id)
        else:
            log.warning("lock_manager.unexpected_status", job_id=self._job_id, status=status)
            await self._pool.release(self._conn)
            self._conn = None
            raise LockNotAcquiredError(f"Unexpected job status for {self._job_id}: {status}")

        # -- Step 4: Set status to RUNNING --
        await self._conn.execute(Queries.SET_RUNNING, self._job_id)
        log.info("lock_manager.acquired", job_id=self._job_id, previous_status=status)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._conn is None:
            return
        try:
            if exc_type is None:
                await self._conn.execute(Queries.SET_IDLE, self._job_id)
                log.info("lock_manager.released_idle", job_id=self._job_id)
            else:
                error_msg = str(exc_val) if exc_val else "Unknown error"
                await self._conn.execute(Queries.SET_FAILED, self._job_id, error_msg)
                log.error("lock_manager.released_failed", job_id=self._job_id, error=error_msg)
        finally:
            await self._pool.release(self._conn)
            self._conn = None

    async def signal_pause(
        self,
        post_id: str,
        cursor: str,
        attempt: int,
    ) -> None:
        """
        Called by C5's RecoveryManager when a rate limit is hit.
        Persists the pause state to schedule_state.
        """
        from modules.recovery import compute_resume_at

        resume_at = compute_resume_at(attempt - 1)
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                Queries.SET_PAUSED,
                self._job_id,
                cursor,
                post_id,
                resume_at,
                attempt,
            )

        log.warning(
            "lock_manager.paused",
            job_id=self._job_id,
            post_id=post_id,
            attempt=attempt,
            resume_at=resume_at.isoformat(),
        )

    async def get_resume_state(self) -> Optional[dict[str, Any]]:
        """Returns the saved post_id and cursor if the job was previously paused."""
        return self.resume_state

    # -- Private --

    async def _reset_zombie_if_stale(self) -> None:
        """
        If a RUNNING job has a heartbeat older than 5 minutes, it is a zombie.
        Reset status to IDLE.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(Queries.RESET_ZOMBIE, self._job_id)
        if result == "UPDATE 1":
            log.warning("lock_manager.zombie_reset", job_id=self._job_id)

    async def _ensure_job_row(self) -> None:
        """Create a schedule_state row for newly added scraper sources."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(Queries.ENSURE_JOB_ROW, self._job_id, self._source_id, self._platform)

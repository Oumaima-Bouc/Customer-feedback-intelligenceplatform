"""
C2 - Scheduler & Orchestrator
scheduler/job.py
APScheduler setup with PostgreSQL job store.
Defines run_pipeline() - the main 4-phase pipeline orchestrator.
Wires together C3, C4, and C5 components into a single execution unit.
Supports multiple sources (Facebook pages, Instagram accounts).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from shared.job_tracker import JobTracker
from db.connection import get_pool, _build_dsn
from modules.lock_manager import LockManager, LockNotAcquiredError
from modules.heartbeat import run_heartbeat
from modules.connection_manager import (
    upsert_job_instance_sync,
    set_job_instance_status_sync,
    publish_page_usage_sync,
)

# Seconds before a freshly-added source runs for the first time ("upcoming run").
NEW_SOURCE_RUN_DELAY_SECONDS = 15

# C3 imports
from modules.discovery import run_discovery
from modules.comment_engine import run_comment_ingestion

# C4 imports
from modules.validity_checker import run_post_validity_check
from modules.like_sync import run_like_sync
from modules.persistence import run_persistence

# C5 imports
from modules.rate_guard import RateGuard, APIQuotaWarning, APIRateLimitException
from modules.recovery import RecoveryManager

# C3 graph client
from api.graph_client import GraphClient

log = structlog.get_logger(__name__)


# -- Pipeline --

async def _load_source(source_id: int) -> dict:
    """Fetch source configuration from scraping_sources table."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, platform, external_id, name, access_token, is_active, health_status "
            "FROM scraping_sources WHERE id = $1",
            source_id,
        )
    if row is None:
        raise ValueError(f"Source {source_id} not found in scraping_sources")
    return dict(row)


async def run_pipeline(source_id: int) -> None:
    """
    Main pipeline entry point - called by APScheduler per source.

    Phase 0: Acquire lock (exit immediately if another run is active for this source).
    Phase 0b: Post validity pre-check (C4).
    Phase 1: Discovery - fetch active posts (C3).
    Phase 2: Comment ingestion - differential sync (C3).
    Phase 3: Like-weight sync - batch like_count refresh (C4).
    Phase 4: Persistence - UPSERT comments to DB (C4).
    Cleanup: Release lock -> IDLE.
    """
    source = await _load_source(source_id)
    if not source["is_active"]:
        log.info("pipeline.skipped_inactive_source", source_id=source_id)
        return

    platform = source["platform"]
    external_id = source["external_id"]
    job_id = f"{platform}_scraper_{external_id}"

    log.info("pipeline.start", source_id=source_id, platform=platform, external_id=external_id)

    # -- Job tracker (async, uses asyncpg DSN) --
    asyncpg_dsn = _build_dsn().replace("postgresql+asyncpg://", "postgresql://")
    tracker = JobTracker(dsn=asyncpg_dsn, service="ai-service-b")

    async with tracker.start("fb_scraper", page_id=external_id) as job:
        # -- Instantiate shared components for this run --
        rate_guard = RateGuard(settings.rate_limit_threshold, settings.like_skip_threshold)
        lock_manager = LockManager(job_id=job_id, source_id=source_id, platform=platform)
        recovery = RecoveryManager(signal_pause_fn=lock_manager.signal_pause)

        try:
            async with lock_manager:
                await _set_instance(job_id, "running")
                resume_state = lock_manager.resume_state
                result = await _run_phases(
                    rate_guard, recovery, lock_manager, resume_state,
                    platform=platform, external_id=external_id,
                    source_id=source_id,
                    access_token=source.get("access_token") or settings.meta_access_token,
                )
                if result:
                    job.set_counts(records_in=result.get("posts", 0), records_out=result.get("comments", 0))
                    job.add_metadata(source_id=source_id, platform=platform, **result)

                    # Update source stats
                    pool = await get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE scraping_sources SET last_scraped_at = NOW(), "
                            "total_comments_scraped = total_comments_scraped + $1 "
                            "WHERE id = $2",
                            result.get("comments", 0), source_id,
                        )
        except LockNotAcquiredError:
            log.info("pipeline.skipped_concurrent_run", job_id=job_id)
            job.log("INFO", "pipeline.skipped", "Concurrent run already active")
            return
        except (APIQuotaWarning, APIRateLimitException) as exc:
            log.warning("pipeline.rate_limited", job_id=job_id, reason=str(exc))
            job.log("WARNING", "pipeline.rate_limited", str(exc))
            await _set_instance(job_id, "paused")
        except Exception as exc:
            log.error("pipeline.unhandled_error", job_id=job_id, error=str(exc), exc_info=True)
            await _set_instance(job_id, "error")
            raise
        else:
            log.info("pipeline.complete", job_id=job_id)
            job.log("INFO", "pipeline.complete", "All phases done")
            await _set_instance(job_id, "idle", mark_run=True)

        # Publish this page's latest API usage for reply scrape/reply coordination.
        try:
            await asyncio.to_thread(publish_page_usage_sync, source_id, rate_guard.quota_pct)
        except Exception:  # noqa: BLE001 — coordination signal is best-effort
            pass


async def _run_phases(
    rate_guard: RateGuard,
    recovery: RecoveryManager,
    lock_manager: LockManager,
    resume_state: Optional[dict],
    platform: str,
    external_id: str,
    source_id: int,
    access_token: str,
) -> Optional[dict]:
    """Executes all 4 phases with heartbeat running in the background."""
    job_id = f"{platform}_scraper_{external_id}"
    heartbeat_task = asyncio.create_task(run_heartbeat(job_id))

    try:
        async with GraphClient(
            base_url=settings.graph_base_url,
            access_token=access_token,
            rate_guard=rate_guard,
            max_attempts=settings.retry_max_attempts,
            recovery=recovery,
        ) as client:
            # -- Refresh the source's public name so the dashboard stays in sync --
            # If the page owner renames the page on Facebook, the new name is
            # picked up here and reflected in the UI on the next run.
            await _refresh_source_name(client, source_id=source_id, platform=platform, external_id=external_id)

            # -- Phase 0b: Post validity pre-check (C4) --
            log.info("pipeline.phase.validity_check", job_id=job_id)
            valid_post_ids = await run_post_validity_check(client, source_id=source_id)

            # -- Phase 1: Discovery (C3) --
            log.info("pipeline.phase.discovery", job_id=job_id)
            active_post_ids = await run_discovery(client, external_id=external_id, source_id=source_id)
            scrape_ids = active_post_ids

            # -- Phase 2: Comment ingestion (C3) --
            log.info("pipeline.phase.comment_ingestion", job_id=job_id, post_count=len(scrape_ids))
            staged_comments = await run_comment_ingestion(
                client=client,
                recovery=recovery,
                post_ids=scrape_ids,
                source=platform,
                resume_state=resume_state,
            )

            # -- Phase 3: Like-weight sync (C4) --
            log.info("pipeline.phase.like_sync", job_id=job_id)
            await run_like_sync(
                client=client,
                rate_guard=rate_guard,
                post_ids=scrape_ids,
            )

            # -- Phase 4: Persistence (C4) --
            log.info("pipeline.phase.persistence", job_id=job_id, comment_count=len(staged_comments))
            persisted = await run_persistence(staged_comments)
            log.info("pipeline.phase.persistence.done", job_id=job_id, persisted=persisted)

            return {"posts": len(scrape_ids), "comments": persisted}

    except (APIQuotaWarning, APIRateLimitException):
        raise
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


async def _refresh_source_name(
    client: GraphClient,
    source_id: int,
    platform: str,
    external_id: str,
) -> None:
    """Fetch the page/profile's current public name and persist it (best-effort)."""
    try:
        fields = "id,name,username" if platform == "instagram" else "id,name"
        meta = await client.get(f"/{external_id}", {"fields": fields})
        fresh_name = meta.get("name") or meta.get("username")
        if fresh_name:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE scraping_sources SET name = $1, health_status = 'healthy', "
                    "updated_at = NOW() WHERE id = $2",
                    fresh_name, source_id,
                )
            log.info("pipeline.name_refreshed", source_id=source_id, name=fresh_name)
    except Exception as exc:  # noqa: BLE001 — never let a name refresh break a run
        log.warning("pipeline.name_refresh_failed", source_id=source_id, error=str(exc))


async def _set_instance(
    job_name: str,
    status: str,
    *,
    mark_run: bool = False,
    is_enabled: Optional[bool] = None,
) -> None:
    """Best-effort update of the scraping_job_instances tracking row."""
    try:
        await asyncio.to_thread(
            set_job_instance_status_sync, job_name, status, is_enabled, mark_run
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("pipeline.job_instance_update_failed", job_name=job_name, error=str(exc))


# -- Scheduler Setup --

def _job_id_for(platform: str, external_id: str) -> str:
    return f"{platform}_scraper_{external_id}"


def add_source_job(
    scheduler: AsyncIOScheduler,
    source: dict,
    *,
    start_date: Optional[datetime] = None,
    run_soon: bool = False,
) -> "Any":
    """
    Add (or replace) the recurring scrape job for a single source and record a
    scraping_job_instances tracking row.

    - run_soon=True schedules the first run a few seconds out (used when a new
      source is added live, so it is scraped in the upcoming cycle).
    - Thread-safe: may be called from the health-server thread.
    """
    source_id = source["id"]
    platform = source["platform"]
    external_id = source["external_id"]
    job_id = _job_id_for(platform, external_id)

    now = datetime.now(timezone.utc)
    if start_date is None:
        delay = NEW_SOURCE_RUN_DELAY_SECONDS if run_soon else settings.scraper_stagger_seconds
        start_date = now + timedelta(seconds=delay)

    job = scheduler.add_job(
        run_pipeline,
        trigger=IntervalTrigger(hours=settings.scraper_interval_h, start_date=start_date),
        id=job_id,
        args=[source_id],
        replace_existing=True,
        max_instances=1,
    )

    # Mirror the schedule into the tracking table (best-effort).
    try:
        upsert_job_instance_sync(
            source_id=source_id,
            job_name=job_id,
            next_run_time=getattr(job, "next_run_time", None),
            is_enabled=True,
            status="idle",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("scheduler.job_instance_upsert_failed", job_id=job_id, error=str(exc))

    log.info(
        "scheduler.job_added",
        job_id=job_id,
        source_id=source_id,
        platform=platform,
        external_id=external_id,
        start_date=start_date.isoformat(),
        run_soon=run_soon,
    )
    return job


def remove_source_job(scheduler: AsyncIOScheduler, platform: str, external_id: str) -> bool:
    """Remove a source's scrape job and disable its tracking row. Idempotent."""
    job_id = _job_id_for(platform, external_id)
    removed = False
    try:
        scheduler.remove_job(job_id)
        removed = True
    except JobLookupError:
        removed = False
    try:
        set_job_instance_status_sync(job_id, status="paused", is_enabled=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("scheduler.job_instance_disable_failed", job_id=job_id, error=str(exc))
    log.info("scheduler.job_removed", job_id=job_id, removed=removed)
    return removed


def create_scheduler(sources: list[dict]) -> AsyncIOScheduler:
    """
    Creates and configures the APScheduler instance with one job per source.
    - PostgreSQL job store ensures the schedule survives restarts.
    - Staggered start times prevent all sources from firing simultaneously.
    - misfire_grace_time enables catch-up for missed runs.
    - max_instances=1 prevents concurrent runs per source.
    """
    sync_dsn = _build_dsn().replace("postgresql+asyncpg://", "postgresql://")

    jobstores = {
        "default": SQLAlchemyJobStore(url=sync_dsn, tablename="apscheduler_jobs"),
    }

    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
        },
        timezone="UTC",
    )

    stagger_seconds = settings.scraper_stagger_seconds
    now = datetime.now(timezone.utc)

    for i, source in enumerate(sources):
        add_source_job(
            scheduler,
            source,
            start_date=now + timedelta(seconds=i * stagger_seconds),
        )

    log.info(
        "scheduler.configured",
        interval_hours=settings.scraper_interval_h,
        stagger_seconds=stagger_seconds,
        total_sources=len(sources),
    )
    return scheduler

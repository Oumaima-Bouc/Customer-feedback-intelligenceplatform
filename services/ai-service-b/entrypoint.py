"""
AI Service B — Meta Scraper Entrypoint.

1. Connects to Consul, loads config
2. Starts FastAPI health server (background thread)
3. Registers SIGTERM for graceful shutdown
4. Starts APScheduler-based scraper pipeline
5. Blocks until SIGTERM
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

import logging_config  # noqa: F401  # configure JSONL logging before startup logs

from shared.config_lib.manager import ConfigManager
from shared.config_lib.schema import AIServiceBConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
config_manager: ConfigManager | None = None
shutdown_event = asyncio.Event()


def _apply_config_to_settings(cfg: AIServiceBConfig | None) -> None:
    """Copy Consul config into the module-level settings singleton."""
    if cfg is None:
        return
    from config import settings
    settings.rate_limit_threshold = cfg.thresholds.rate_limit_threshold
    settings.max_active_posts = cfg.thresholds.max_active_posts
    settings.max_post_age_h = cfg.thresholds.max_post_age_h
    settings.scrape_replies = cfg.thresholds.scrape_replies
    settings.reply_max_depth = cfg.thresholds.reply_max_depth
    settings.scraper_interval_h = cfg.scheduler.scraper_interval_h
    settings.scraper_stagger_seconds = cfg.scheduler.scraper_stagger_seconds
    settings.job_timeout_m = cfg.scheduler.job_timeout_m
    settings.semaphore_limit = cfg.runtime.semaphore_limit
    settings.retry_max_attempts = cfg.runtime.retry_max_attempts
    settings.batch_like_size = cfg.runtime.batch_like_size


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------
health_app = FastAPI(title="AI Service B — Meta Scraper")


@health_app.get("/health")
async def health_check():
    from fastapi.responses import JSONResponse
    checks = {
        "alive": True,
        "config_loaded": config_manager is not None and config_manager.get_config() is not None,
        "maintenance_mode": config_manager.is_maintenance_mode() if config_manager else False,
    }
    # DB check — the pool lives in the main event loop (different thread),
    # so we probe the DB directly with a short-lived synchronous-style check
    # rather than reusing the asyncpg pool which is bound to another loop.
    try:
        import asyncpg
        from db.connection import _build_dsn
        dsn = _build_dsn()
        conn = await asyncpg.connect(dsn=dsn, timeout=5)
        await conn.fetchval("SELECT 1")
        await conn.close()
        checks["db_connected"] = True
    except Exception:
        checks["db_connected"] = False

    all_ok = checks["alive"] and checks["config_loaded"] and checks["db_connected"]
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "healthy" if all_ok else "degraded", "checks": checks},
    )


@health_app.get("/config")
async def get_current_config():
    if config_manager is None:
        return {"error": "not initialized"}
    cfg = config_manager.get_config()
    return {
        "version": config_manager.get_version(),
        "config": cfg.model_dump() if cfg else None,
    }


@health_app.post("/internal/scrape/run")
async def trigger_scrape_run():
    """Trigger an immediate scrape for every active source — the manual "run now"
    button. Fire-and-forget on the scheduler's loop: each run acquires the per-source
    lock and exits cleanly if a scheduled run is already active (no overlap, no double
    scrape). The recurring schedule is untouched. The dashboard polls job_executions
    to detect when the scrape has finished before kicking off the pipeline."""
    from fastapi.responses import JSONResponse
    from scheduler.state import get_active_scheduler, get_scheduler_loop
    from scheduler.job import run_pipeline

    scheduler = get_active_scheduler()
    loop = get_scheduler_loop()
    if scheduler is None or loop is None:
        return JSONResponse(status_code=503, content={"started": 0, "error": "Scheduler not ready"})

    source_ids = [job.args[0] for job in scheduler.get_jobs() if job.args]
    for sid in source_ids:
        asyncio.run_coroutine_threadsafe(run_pipeline(sid), loop)

    logger.info("scrape.manual_run_triggered", extra={"sources": len(source_ids)})
    return {"started": len(source_ids), "source_ids": source_ids}


# ---------------------------------------------------------------------------
# Source control endpoints (called by the dashboard backend)
# ---------------------------------------------------------------------------
class _ValidateRequest(BaseModel):
    platform: str
    external_id: str
    access_token: str = ""


@health_app.post("/sources/validate")
async def sources_validate(req: _ValidateRequest):
    """Live-test a page/profile connection and return its current public name."""
    from modules.connection_manager import validate_connection
    return await validate_connection(req.platform, req.external_id, req.access_token)


@health_app.post("/sources/{source_id}/schedule")
async def sources_schedule(source_id: int):
    """
    Create/replace the recurring scrape job for a source and run it in the
    upcoming cycle. Schedule mutation is marshaled onto the scheduler's loop.
    """
    from fastapi.responses import JSONResponse
    from scheduler.state import get_active_scheduler, get_scheduler_loop
    from scheduler.job import add_source_job
    from modules.connection_manager import get_source_sync

    scheduler = get_active_scheduler()
    loop = get_scheduler_loop()
    if scheduler is None or loop is None:
        return JSONResponse(status_code=503, content={"scheduled": False, "error": "Scheduler not ready"})

    source = await asyncio.to_thread(get_source_sync, source_id)
    if source is None:
        return JSONResponse(status_code=404, content={"scheduled": False, "error": "Source not found"})

    async def _add():
        return add_source_job(scheduler, source, run_soon=True)

    try:
        job = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(_add(), loop))
    except Exception as exc:  # noqa: BLE001
        logger.error("sources_schedule.failed", extra={"source_id": source_id, "error": str(exc)})
        return JSONResponse(status_code=500, content={"scheduled": False, "error": str(exc)})

    next_run = job.next_run_time.isoformat() if getattr(job, "next_run_time", None) else None
    return {"scheduled": True, "source_id": source_id, "next_run_time": next_run}


@health_app.post("/sources/{source_id}/unschedule")
async def sources_unschedule(source_id: int):
    """Remove a source's scrape job (used on pause / delete)."""
    from fastapi.responses import JSONResponse
    from scheduler.state import get_active_scheduler, get_scheduler_loop
    from scheduler.job import remove_source_job
    from modules.connection_manager import get_source_sync

    source = await asyncio.to_thread(get_source_sync, source_id)
    if source is None:
        return JSONResponse(status_code=404, content={"unscheduled": False, "error": "Source not found"})

    scheduler = get_active_scheduler()
    loop = get_scheduler_loop()
    if scheduler is None or loop is None:
        return JSONResponse(status_code=503, content={"unscheduled": False, "error": "Scheduler not ready"})

    async def _remove():
        return remove_source_job(scheduler, source["platform"], source["external_id"])

    try:
        removed = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(_remove(), loop))
    except Exception as exc:  # noqa: BLE001
        logger.error("sources_unschedule.failed", extra={"source_id": source_id, "error": str(exc)})
        return JSONResponse(status_code=500, content={"unscheduled": False, "error": str(exc)})

    return {"unscheduled": True, "removed": removed}


@health_app.post("/sources/{source_id}/refresh")
async def sources_refresh(source_id: int):
    """Re-test a source's connection and refresh its stored public name + health."""
    from fastapi.responses import JSONResponse
    from modules.connection_manager import (
        get_source_sync,
        update_source_health_sync,
        validate_connection,
    )
    from config import settings as _settings

    source = await asyncio.to_thread(get_source_sync, source_id)
    if source is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "Source not found"})

    token = source.get("access_token") or _settings.meta_access_token
    result = await validate_connection(source["platform"], source["external_id"], token)
    if result.get("ok"):
        # Healthy ONLY when comment-scrape permission is granted. Reasons are
        # passed through (None clears them on a now-healthy/repliable refresh).
        can_scrape = bool(result.get("can_scrape", False))
        await asyncio.to_thread(
            update_source_health_sync, source_id,
            name=result.get("name"),
            health_status="healthy" if can_scrape else "error",
            last_error=result.get("scrape_reason"),
            can_reply=bool(result.get("can_reply", False)),
            reply_perm_error=result.get("reply_reason"),
        )
    else:
        await asyncio.to_thread(update_source_health_sync, source_id, name=None, health_status="error", last_error=result.get("error"))
    return result


# ---------------------------------------------------------------------------
# Hot-reload handlers
# ---------------------------------------------------------------------------
def on_threshold_change(key: str, old_val, new_val):
    """Update scraper runtime thresholds in-memory."""
    logger.info("hot_reload.threshold", extra={"key": key, "old": old_val, "new": new_val})
    try:
        from config import settings
        if key == "thresholds.rate_limit_threshold":
            settings.rate_limit_threshold = new_val
        elif key == "thresholds.max_active_posts":
            settings.max_active_posts = new_val
        elif key == "thresholds.max_post_age_h":
            settings.max_post_age_h = new_val
        elif key == "thresholds.scrape_replies":
            settings.scrape_replies = new_val
    except Exception as exc:
        logger.error("hot_reload.apply_failed", extra={"error": str(exc)})


def on_runtime_change(key: str, old_val, new_val):
    logger.info("hot_reload.runtime", extra={"key": key, "old": old_val, "new": new_val})
    try:
        from config import settings
        if key == "runtime.semaphore_limit":
            settings.semaphore_limit = new_val
        elif key == "runtime.retry_max_attempts":
            settings.retry_max_attempts = new_val
    except Exception as exc:
        logger.error("hot_reload.apply_failed", extra={"error": str(exc)})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_health_server():
    uvicorn.run(health_app, host="0.0.0.0", port=8081, log_level="warning")


async def _load_active_sources() -> list[dict]:
    """Fetch all active scraping sources from the database."""
    from config import settings
    from db.connection import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, platform, external_id, name, is_active "
            "FROM scraping_sources WHERE is_active = TRUE ORDER BY id"
        )
        return [dict(r) for r in rows]


async def run_scraper():
    """Import and run the original scraper main()."""
    from config import settings
    from db.connection import close_pool, check_connection
    from scheduler.job import create_scheduler

    # Load active sources
    sources = await _load_active_sources()
    logger.info(
        "scraper.startup",
        extra={
            "interval_hours": settings.scraper_interval_h,
            "stagger_seconds": settings.scraper_stagger_seconds,
            "sources_count": len(sources),
            "sources": [s["external_id"] for s in sources],
        },
    )

    # Verify DB
    if not await check_connection():
        logger.error("scraper.db_check.failed")
        sys.exit(1)
    logger.info("scraper.db_check.ok")

    # Validate interval sufficiency
    if sources:
        min_interval_hours = (len(sources) * settings.scraper_stagger_seconds) / 3600
        if settings.scraper_interval_h < min_interval_hours:
            logger.warning(
                "scraper.interval_insufficient",
                interval_hours=settings.scraper_interval_h,
                required_hours=min_interval_hours,
                source_count=len(sources),
            )

    # Start scheduler with per-source jobs
    scheduler = create_scheduler(sources)
    scheduler.start()
    # Expose the scheduler + its loop so the control endpoints (health-server
    # thread) can add/remove jobs dynamically without a restart.
    from scheduler.state import set_active_scheduler
    set_active_scheduler(scheduler, asyncio.get_running_loop())
    logger.info("scraper.scheduler_started")

    # Wait for shutdown
    await shutdown_event.wait()

    # Graceful shutdown
    logger.info("scraper.shutting_down")
    scheduler.shutdown(wait=True)
    await close_pool()
    logger.info("scraper.stopped")


def main():
    global config_manager

    # 1. SIGTERM handling
    def handle_signal(*_):
        logger.info("sigterm_received")
        shutdown_event.set()

    # 2. ConfigManager
    service_name = os.environ.get("SERVICE_NAME", "ai-service-b")
    config_manager = ConfigManager(service_name=service_name)
    try:
        config_manager.start()
    except Exception as exc:
        logger.critical("config_manager_start_failed", exc_info=exc)
        sys.exit(1)
    cfg = config_manager.get_config()
    if isinstance(cfg, AIServiceBConfig):
        _apply_config_to_settings(cfg)

    # 3. Register hot-reload handlers
    config_manager.reload_registry.register("thresholds.rate_limit_threshold", on_threshold_change)
    config_manager.reload_registry.register("thresholds.max_active_posts", on_threshold_change)
    config_manager.reload_registry.register("thresholds.max_post_age_h", on_threshold_change)
    config_manager.reload_registry.register("thresholds.scrape_replies", on_threshold_change)
    config_manager.reload_registry.register("runtime.semaphore_limit", on_runtime_change)
    config_manager.reload_registry.register("runtime.retry_max_attempts", on_runtime_change)

    # 4. Health server in background
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    # 5. Check maintenance mode
    if config_manager.is_maintenance_mode():
        logger.warning("maintenance_mode_active_scraper_idle")
        shutdown_event.wait()
    else:
        # 6. Run the async scraper
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)

        try:
            loop.run_until_complete(run_scraper())
        finally:
            config_manager.stop()
            loop.close()


if __name__ == "__main__":
    main()

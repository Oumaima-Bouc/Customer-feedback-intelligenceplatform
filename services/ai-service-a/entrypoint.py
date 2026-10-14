"""
AI Service A — Topic Extraction Pipeline Entrypoint.

Startup sequence:
  1. Connect to Consul, load config (hot-reload watcher starts in background)
  2. Bootstrap application container (models loaded, DB connected)
  3. Start FastAPI health server in a background thread
  4. Register SIGTERM / SIGINT handler for graceful shutdown
  5. Run pipeline immediately on startup (if run_on_startup=True in Consul config)
  6. Start APScheduler with a CronTrigger read from Consul (default: "0 1 * * *")
  7. Keep alive — scheduler fires the pipeline at the configured cron time
  8. On SIGTERM: shut down scheduler, stop config watcher, dispose DB engine

Hot-reloadable via Consul (no restart needed):
  - runtime.schedule_cron      → reschedules the APScheduler job live
  - runtime.run_on_startup     → controls whether restart triggers an immediate run
  - thresholds.*               → picked up by the next pipeline batch
  - runtime.llm_*              → picked up by the next pipeline call

Restart-required via Consul (triggers rolling restart by Restart Orchestrator):
  - model.*                    → model path / device / batch-size changes
  - workers.*                  → pipeline batch-size / max-batches changes
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import uuid
from contextlib import asynccontextmanager

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Ensure /app is on the path so both src.* and shared.* imports resolve.
sys.path.insert(0, "/app")

from shared.config_lib.manager import ConfigManager
from shared.job_tracker import JobTracker
from shared.config_lib.schema import AIServiceAConfig
from shared.logging_lib.setup import configure_service_logging

configure_service_logging(
    service_name=os.environ.get("SERVICE_NAME", "ai-service-a"),
    log_level=os.environ.get("LOG_LEVEL", os.environ.get("APP_LOG_LEVEL", "INFO")),
    log_format=os.environ.get("APP_LOG_FORMAT", "json"),
    log_dir="/logs",
    enable_file_logging=True,
    enable_secret_redaction=True,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
config_manager: ConfigManager | None = None
app_container = None                        # populated by _initialize_app()
pipeline_scheduler: BackgroundScheduler | None = None
shutdown_event = threading.Event()

# Prevents the startup-run thread and the APScheduler thread from
# executing the pipeline at the same time.
_pipeline_lock = threading.Lock()

PIPELINE_JOB_ID  = "daily_topic_extraction"
DEFAULT_CRON     = "0 1 * * *"     # 01:00 every day
DEFAULT_TIMEZONE = "Africa/Algiers"


# ---------------------------------------------------------------------------
# FastAPI health app
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


health_app = FastAPI(title="AI Service A — Topic Extraction", lifespan=lifespan)


@health_app.get("/health")
async def health_check():
    """
    Liveness + readiness probe.
    Returns 200 (healthy) only when:
      - config is loaded
      - DB is reachable
      - models are loaded
      - not in maintenance mode
    Also reports the next scheduled pipeline run time.
    """
    checks: dict = {
        "alive": True,
        "config_loaded": (
            config_manager is not None
            and config_manager.get_config() is not None
        ),
        "maintenance_mode": (
            config_manager.is_maintenance_mode() if config_manager else False
        ),
    }

    if app_container is not None:
        try:
            from sqlalchemy import text
            with app_container.session_factory() as session:
                session.execute(text("SELECT 1"))
            checks["db_connected"] = True
        except Exception:
            checks["db_connected"] = False

        checks["models_loaded"] = True
    else:
        checks["db_connected"] = False
        checks["models_loaded"] = False

    # Scheduler status
    if pipeline_scheduler is not None and pipeline_scheduler.running:
        job = pipeline_scheduler.get_job(PIPELINE_JOB_ID)
        if job and job.next_run_time:
            checks["next_scheduled_run"] = job.next_run_time.isoformat()
        checks["schedule_cron"] = _current_cron()

    checks["pipeline_running"] = _pipeline_lock.locked()

    all_ok = all([
        checks["alive"],
        checks["config_loaded"],
        checks["db_connected"],
        checks["models_loaded"],
        not checks["maintenance_mode"],
    ])

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "healthy" if all_ok else "degraded", "checks": checks},
    )


@health_app.get("/config")
async def get_current_config():
    """Expose current active Consul config (for debugging / dashboard)."""
    if config_manager is None:
        return {"error": "config_manager not initialized"}
    cfg = config_manager.get_config()
    return {
        "version": config_manager.get_version(),
        "config": cfg.model_dump() if cfg else None,
    }


@health_app.post("/internal/pipeline/run")
async def trigger_pipeline_run():
    """Run the analysis pipeline now — the manual "run now" button (pipeline phase).
    Fire-and-forget on a worker thread so the event loop / health probes stay
    responsive. `_run_pipeline` is guarded by `_pipeline_lock`, so it no-ops if a
    scheduled or startup run is already active (no overlap). The recurring schedule is
    untouched. The dashboard polls job_executions to detect completion."""
    if app_container is None:
        return JSONResponse(status_code=503, content={"started": False, "error": "not ready"})
    if _pipeline_lock.locked():
        return {"started": False, "reason": "already_running"}
    threading.Thread(target=_run_pipeline, name="manual-pipeline", daemon=True).start()
    return {"started": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _current_cron() -> str:
    """Return the active cron expression (from Consul or the default)."""
    if config_manager is None:
        return DEFAULT_CRON
    cfg = config_manager.get_config()
    if cfg and isinstance(cfg, AIServiceAConfig):
        return cfg.runtime.schedule_cron
    return DEFAULT_CRON


def _current_timezone() -> str:
    """Return the pipeline timezone (from settings or the default)."""
    if app_container is not None:
        try:
            return app_container.settings.pipeline.window_timezone
        except Exception:
            pass
    return DEFAULT_TIMEZONE


def _apply_runtime_config_to_container(cfg: AIServiceAConfig | None) -> None:
    """Copy hot Consul settings into the already-bootstrapped use-case settings."""
    if app_container is None or cfg is None:
        return
    app_container.settings.pipeline.schedule_cron = cfg.runtime.schedule_cron
    app_container.settings.pipeline.lookback_days = cfg.runtime.lookback_days
    app_container.settings.word_cloud.max_words = cfg.word_cloud.max_words
    app_container.settings.word_cloud.min_frequency = cfg.word_cloud.min_frequency


# ---------------------------------------------------------------------------
# Signal handler
# ---------------------------------------------------------------------------
def handle_sigterm(*_) -> None:
    logger.info("sigterm_received_shutting_down")
    shutdown_event.set()


# ---------------------------------------------------------------------------
# Pipeline bootstrap (once at startup)
# ---------------------------------------------------------------------------
def _initialize_app() -> bool:
    """
    Bootstrap the application container exactly once.
    Loads models, connects to DB, wires all use-cases.
    Returns True on success; False on any failure (caller should sys.exit).
    """
    global app_container
    try:
        from src.app.bootstrap import bootstrap
        app_container = bootstrap()

        if config_manager is not None:
            cfg = config_manager.get_config()
            if cfg and isinstance(cfg, AIServiceAConfig):
                _apply_runtime_config_to_container(cfg)
                logger.info(
                    "pipeline.using_consul_config",
                    extra={"version": config_manager.get_version()},
                )
        return True
    except SystemExit:
        logger.critical("pipeline.bootstrap_failed_system_exit")
        return False
    except Exception as exc:
        logger.critical("pipeline.bootstrap_exception", exc_info=exc)
        return False


# ---------------------------------------------------------------------------
# Pipeline execution (called both on startup and by APScheduler)
# ---------------------------------------------------------------------------
def _run_pipeline() -> None:
    """
    Execute one full pipeline cycle:
      1. Run the daily enrichment pipeline (topic + sentiment for unclassified comments)
      2. Refresh the word-cloud snapshot

    Protected by _pipeline_lock so the startup run and a scheduled run
    can never execute concurrently even if timing overlaps.
    """
    if not _pipeline_lock.acquire(blocking=False):
        logger.warning("pipeline.skipped_already_running")
        return

    cid = str(uuid.uuid4())
    logger.info("pipeline.run_start", extra={"correlation_id": cid})

    try:
        # Re-check maintenance mode at actual run time (not just at startup).
        if config_manager is not None and config_manager.is_maintenance_mode():
            logger.warning(
                "pipeline.skipped_maintenance_mode",
                extra={"correlation_id": cid},
            )
            return

        if app_container is None:
            logger.error(
                "pipeline.container_not_initialized",
                extra={"correlation_id": cid},
            )
            return

        # ── Job tracker ───────────────────────────────────────────────────
        tracker = JobTracker(
            dsn=app_container.settings.database.plain_dsn,
            service="ai-service-a",
            sync=True,
        )

        # ── Main enrichment pipeline ──────────────────────────────────────
        with tracker.start_sync("ml_pipeline", correlation_id=cid) as job:
            job.log("INFO", "pipeline.start", "Starting ML enrichment pipeline")

            app_container.run_daily_use_case.execute(correlation_id=cid)
            logger.info("pipeline.run_complete", extra={"correlation_id": cid})

            job.log("INFO", "pipeline.enrichment_complete", "Topic + sentiment done")
            result = app_container.run_daily_use_case.last_result
            if result:
                job.set_counts(
                    records_in=result.total_processed,
                    records_out=result.total_updated,
                )
                use_case = app_container.run_daily_use_case
                job.add_metadata(
                    batches=result.total_batches,
                    errors=result.total_errors,
                    status=result.status,
                    window_start=(
                        use_case.last_window_start.isoformat()
                        if use_case.last_window_start else None
                    ),
                    window_end=(
                        use_case.last_window_end.isoformat()
                        if use_case.last_window_end else None
                    ),
                )

        # ── Word cloud refresh ────────────────────────────────────────────
        with tracker.start_sync("word_cloud_refresh", correlation_id=cid) as wc_job:
            try:
                count = app_container.refresh_word_cloud_use_case.execute()
                wc_job.set_counts(records_out=count)
                wc_job.log("INFO", "word_cloud.refresh_done", f"{count} words")
                logger.info(
                    "word_cloud.refresh_done",
                    extra={"words": count, "correlation_id": cid},
                )
            except Exception as wc_exc:
                wc_job.log("ERROR", "word_cloud.refresh_failed", str(wc_exc))
                logger.warning("word_cloud.refresh_failed", exc_info=wc_exc)

    except Exception as exc:
        logger.error(
            "pipeline.run_failed",
            exc_info=exc,
            extra={"correlation_id": cid},
        )
    finally:
        _pipeline_lock.release()


# ---------------------------------------------------------------------------
# APScheduler
# ---------------------------------------------------------------------------
def _start_scheduler(cron_expr: str, tz: str) -> BackgroundScheduler:
    """
    Create and start a BackgroundScheduler with the given cron expression.

    Uses an in-memory job store — no extra DB table needed.
    If the container restarts, the pipeline always runs immediately on startup
    (run_on_startup=True) so there is no risk of missing a daily run.

    Job options:
      max_instances=1   → APScheduler will not launch a second job
                          if the previous one is still running
      coalesce=True     → if multiple triggers fire while the job was
                          blocked, collapse them into a single run
      misfire_grace_time=3600 → still run if fired up to 1 h late
                                (e.g. container slow to start)
    """
    scheduler = BackgroundScheduler(timezone=tz)
    trigger = CronTrigger.from_crontab(cron_expr, timezone=tz)
    scheduler.add_job(
        _run_pipeline,
        trigger=trigger,
        id=PIPELINE_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    return scheduler


# ---------------------------------------------------------------------------
# Hot-reload handlers (called by ConfigManager on Consul KV change)
# ---------------------------------------------------------------------------
def on_schedule_cron_change(key: str, old_val, new_val) -> None:
    """
    Hot-reload handler for runtime.schedule_cron.

    Reschedules the APScheduler cron job in-place — no restart required.
    The new cron takes effect immediately; the next run time is logged.
    """
    logger.info(
        "hot_reload.schedule_cron_changed",
        extra={"key": key, "old": old_val, "new": new_val},
    )

    if pipeline_scheduler is None or not pipeline_scheduler.running:
        logger.warning("hot_reload.scheduler_not_running_cannot_reschedule")
        return

    try:
        tz = _current_timezone()
        trigger = CronTrigger.from_crontab(str(new_val), timezone=tz)
        pipeline_scheduler.reschedule_job(PIPELINE_JOB_ID, trigger=trigger)

        job = pipeline_scheduler.get_job(PIPELINE_JOB_ID)
        next_run = (
            job.next_run_time.isoformat()
            if job and job.next_run_time
            else "unknown"
        )
        logger.info(
            "pipeline.schedule_updated",
            extra={"new_cron": new_val, "timezone": tz, "next_run": next_run},
        )
    except Exception as exc:
        logger.error(
            "pipeline.schedule_update_failed",
            exc_info=exc,
            extra={"attempted_cron": new_val},
        )


def on_threshold_change(key: str, old_val, new_val) -> None:
    """Hot-reload handler for threshold changes (picked up by the next batch)."""
    logger.info(
        "hot_reload.threshold_changed",
        extra={"key": key, "old": old_val, "new": new_val},
    )


def on_runtime_change(key: str, old_val, new_val) -> None:
    """Hot-reload handler for general runtime settings."""
    if app_container is not None and key == "runtime.lookback_days":
        app_container.settings.pipeline.lookback_days = int(new_val)
    logger.info(
        "hot_reload.runtime_changed",
        extra={"key": key, "old": old_val, "new": new_val},
    )


def on_word_cloud_change(key: str, old_val, new_val) -> None:
    """Hot-reload word-cloud extraction limits used by the next refresh."""
    if app_container is not None:
        if key == "word_cloud.max_words":
            app_container.settings.word_cloud.max_words = int(new_val)
        elif key == "word_cloud.min_frequency":
            app_container.settings.word_cloud.min_frequency = int(new_val)
    logger.info(
        "hot_reload.word_cloud_changed",
        extra={"key": key, "old": old_val, "new": new_val},
    )


# ---------------------------------------------------------------------------
# Health server (background thread)
# ---------------------------------------------------------------------------
def run_health_server() -> None:
    uvicorn.run(health_app, host="0.0.0.0", port=8080, log_level="warning")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    global config_manager, pipeline_scheduler

    # 1. Register OS signal handlers ────────────────────────────────────────
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    # 2. Connect to Consul + load initial config ─────────────────────────────
    service_name = os.environ.get("SERVICE_NAME", "ai-service-a")
    config_manager = ConfigManager(service_name=service_name)
    try:
        config_manager.start()
    except Exception as exc:
        logger.critical("config_manager_start_failed", exc_info=exc)
        sys.exit(1)

    # 3. Register hot-reload handlers ────────────────────────────────────────
    config_manager.reload_registry.register(
        "thresholds.sentiment_confidence_min", on_threshold_change
    )
    config_manager.reload_registry.register(
        "thresholds.cluster_merge_similarity", on_threshold_change
    )
    config_manager.reload_registry.register(
        "thresholds.top_k_representatives", on_threshold_change
    )
    config_manager.reload_registry.register(
        "runtime.llm_enabled", on_runtime_change
    )
    config_manager.reload_registry.register(
        "runtime.llm_api_base_url", on_runtime_change
    )
    config_manager.reload_registry.register(
        "runtime.fallback_topic_label", on_runtime_change
    )
    config_manager.reload_registry.register(
        "runtime.lookback_days", on_runtime_change
    )
    config_manager.reload_registry.register(
        "runtime.run_on_startup", on_runtime_change
    )
    config_manager.reload_registry.register(
        "word_cloud.max_words", on_word_cloud_change
    )
    config_manager.reload_registry.register(
        "word_cloud.min_frequency", on_word_cloud_change
    )
    # NEW: schedule_cron is hot-reloadable — APScheduler reschedules live
    config_manager.reload_registry.register(
        "runtime.schedule_cron", on_schedule_cron_change
    )

    # 4. Bootstrap application container ─────────────────────────────────────
    #    (loads models, connects to DB — blocking, must finish before serving)
    if not _initialize_app():
        config_manager.stop()
        sys.exit(1)

    # 5. Read schedule config from Consul ────────────────────────────────────
    cfg = config_manager.get_config()
    cron_expr    = DEFAULT_CRON
    run_on_start = True
    tz           = _current_timezone()

    if cfg and isinstance(cfg, AIServiceAConfig):
        cron_expr    = cfg.runtime.schedule_cron
        run_on_start = cfg.runtime.run_on_startup

    # 6. Start health server in background thread ────────────────────────────
    health_thread = threading.Thread(
        target=run_health_server, name="health-server", daemon=True
    )
    health_thread.start()
    logger.info("health_server_started", extra={"port": 8080})

    # 7. Optional startup run (immediate, non-blocking) ──────────────────────
    #    Runs in its own daemon thread so the scheduler can start immediately
    #    and the health endpoint becomes responsive without waiting.
    if run_on_start and not config_manager.is_maintenance_mode():
        logger.info("pipeline.startup_run_triggered")
        startup_thread = threading.Thread(
            target=_run_pipeline, name="startup-pipeline", daemon=True
        )
        startup_thread.start()
    elif config_manager.is_maintenance_mode():
        logger.warning("maintenance_mode_active_skipping_startup_run")

    # 8. Start the APScheduler cron ──────────────────────────────────────────
    pipeline_scheduler = _start_scheduler(cron_expr, tz)

    job = pipeline_scheduler.get_job(PIPELINE_JOB_ID)
    next_run = (
        job.next_run_time.isoformat() if job and job.next_run_time else "unknown"
    )
    logger.info(
        "pipeline.scheduler_started",
        extra={"cron": cron_expr, "timezone": tz, "next_run": next_run},
    )

    # 9. Block main thread until SIGTERM / SIGINT ────────────────────────────
    logger.info("service_running_waiting_for_shutdown_or_trigger")
    shutdown_event.wait()

    # 10. Graceful shutdown ──────────────────────────────────────────────────
    logger.info("graceful_shutdown_start")

    # Stop scheduler first — prevent new jobs from firing during teardown
    pipeline_scheduler.shutdown(wait=False)

    # Stop config watcher thread
    config_manager.stop()

    # Release DB connection pool
    if app_container is not None:
        try:
            app_container.engine.dispose()
        except Exception:
            pass

    logger.info("graceful_shutdown_complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()

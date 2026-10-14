"""
Reply Service — Group Reply dispatcher entrypoint.

This (foundation) pass wires the ENQUEUE path:
  1. Configure JSON logging (shared/logging_lib)
  2. Connect to Consul, load config/reply-service, start the hot-reload watcher
  3. Start the FastAPI health + control server on a background thread (port 8083)
  4. Block until SIGTERM/SIGINT

The dispatcher (claim -> pace -> send -> coordinate with the scraper) is added in
the send-path pass; the enqueue path + /internal/replies is fully functional here.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading

import uvicorn

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from shared.logging_lib.setup import configure_service_logging

configure_service_logging(
    service_name=os.environ.get("SERVICE_NAME", "reply-service"),
    log_level=os.environ.get("LOG_LEVEL", "INFO"),
    log_format="json",
    log_dir="/logs",
    enable_file_logging=True,
    enable_secret_redaction=True,
)

from shared.config_lib.manager import ConfigManager
from shared.config_lib.schema import ReplyServiceConfig

logger = logging.getLogger(__name__)

config_manager: ConfigManager | None = None


def _apply_config(cfg) -> None:
    """Copy Consul config/reply-service values into the settings singleton."""
    if not isinstance(cfg, ReplyServiceConfig):
        return
    from config import settings
    settings.window_hours = cfg.window.hours
    settings.capacity_daily_per_page = cfg.capacity.daily_per_page
    settings.capacity_max_backlog_days = cfg.capacity.max_backlog_days
    settings.reply_usage_ceiling = cfg.coordination.reply_usage_ceiling
    settings.reply_min_per_hour = cfg.coordination.reply_min_per_hour
    settings.reply_max_per_minute = cfg.pacing.reply_max_per_minute
    settings.dispatch_tick_seconds = cfg.dispatch.tick_seconds
    settings.worker_pool_size = cfg.dispatch.worker_pool_size
    settings.send_max_attempts = cfg.send.max_attempts
    settings.send_claim_timeout_seconds = cfg.send.claim_timeout_seconds


def _on_config_change(key: str, old_val, new_val) -> None:
    _apply_config(config_manager.get_config() if config_manager else None)
    logger.info("hot_reload.reply_config", extra={"key": key, "old": old_val, "new": new_val})


def run_health_server() -> None:
    from api.health_control import health_app
    uvicorn.run(health_app, host="0.0.0.0", port=8083, log_level="warning")


def main() -> None:
    global config_manager

    service_name = os.environ.get("SERVICE_NAME", "reply-service")
    config_manager = ConfigManager(service_name=service_name)
    try:
        config_manager.start()
    except Exception as exc:
        logger.critical("config_manager_start_failed", exc_info=exc)
        sys.exit(1)

    _apply_config(config_manager.get_config())
    for key in (
        "window.hours",
        "capacity.daily_per_page",
        "capacity.max_backlog_days",
        "coordination.reply_usage_ceiling",
        "coordination.reply_min_per_hour",
        "pacing.reply_max_per_minute",
        "dispatch.tick_seconds",
        "send.max_attempts",
        "send.claim_timeout_seconds",
    ):
        config_manager.reload_registry.register(key, _on_config_change)

    # Expose the config manager to the control API (for GET /config).
    from api import health_control
    health_control.config_manager = config_manager

    # Enqueue/control server runs on its own thread (sync psycopg2);
    # the dispatcher runs on the main event loop (asyncpg).
    health_thread = threading.Thread(target=run_health_server, name="health-server", daemon=True)
    health_thread.start()
    logger.info("reply_service.started", extra={"port": 8083})

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    shutdown = asyncio.Event()

    def _trigger_shutdown():
        logger.info("sigterm_received")
        shutdown.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _trigger_shutdown)
        except NotImplementedError:  # pragma: no cover — non-container (Windows) fallback
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(shutdown.set))

    from dispatch.coordinator import run_dispatcher

    try:
        loop.run_until_complete(run_dispatcher(shutdown))
    finally:
        config_manager.stop()
        loop.close()
        logger.info("reply_service.stopped")


if __name__ == "__main__":
    main()

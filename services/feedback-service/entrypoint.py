"""
Feedback Service — Label Feedback entrypoint.

  1. Configure JSON logging (shared/logging_lib)
  2. Connect to Consul, load config/feedback-service, start the hot-reload watcher
  3. Start the FastAPI health + control server on a background thread (port 8084)
  4. Block until SIGTERM/SIGINT

No background loop in this pass (the optional export scheduler is deferred); the
correction + export endpoints are fully functional.
"""
from __future__ import annotations

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
    service_name=os.environ.get("SERVICE_NAME", "feedback-service"),
    log_level=os.environ.get("LOG_LEVEL", "INFO"),
    log_format="json",
    log_dir="/logs",
    enable_file_logging=True,
    enable_secret_redaction=True,
)

from shared.config_lib.manager import ConfigManager
from shared.config_lib.schema import FeedbackServiceConfig

logger = logging.getLogger(__name__)

config_manager: ConfigManager | None = None
_shutdown = threading.Event()


def _apply_config(cfg) -> None:
    if not isinstance(cfg, FeedbackServiceConfig):
        return
    from config import settings
    settings.topic_max_len = cfg.topic.max_len
    settings.topic_allow_digits_if_not_only = cfg.topic.allow_digits_if_not_only
    settings.read_recompute_cache_ttl_seconds = cfg.read.recompute_cache_ttl_seconds
    settings.read_run_boundary_source = cfg.read.run_boundary_source
    settings.export_schedule_cron = cfg.export.schedule_cron
    settings.similarity_enabled = cfg.similarity.enabled


def _on_config_change(key: str, old_val, new_val) -> None:
    _apply_config(config_manager.get_config() if config_manager else None)
    logger.info("hot_reload.feedback_config", extra={"key": key, "new": new_val})


def run_health_server() -> None:
    from api.health_control import health_app
    uvicorn.run(health_app, host="0.0.0.0", port=8084, log_level="warning")


def main() -> None:
    global config_manager

    def handle_signal(*_):
        logger.info("sigterm_received")
        _shutdown.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    config_manager = ConfigManager(service_name=os.environ.get("SERVICE_NAME", "feedback-service"))
    try:
        config_manager.start()
    except Exception as exc:
        logger.critical("config_manager_start_failed", exc_info=exc)
        sys.exit(1)

    _apply_config(config_manager.get_config())
    for key in (
        "topic.max_len",
        "topic.allow_digits_if_not_only",
        "read.recompute_cache_ttl_seconds",
        "read.run_boundary_source",
        "export.schedule_cron",
        "similarity.enabled",
    ):
        config_manager.reload_registry.register(key, _on_config_change)

    from api import health_control
    health_control.config_manager = config_manager

    health_thread = threading.Thread(target=run_health_server, name="health-server", daemon=True)
    health_thread.start()
    logger.info("feedback_service.started", extra={"port": 8084})

    _shutdown.wait()
    config_manager.stop()
    logger.info("feedback_service.stopped")


if __name__ == "__main__":
    main()

"""
manager.py — ConfigManager: Consul-backed distributed configuration for each service.

Responsibilities:
  - Connects to Consul on startup
  - Loads initial config from Consul KV
  - Watches for changes using Consul blocking queries (NOT polling)
  - Validates incoming config via Pydantic
  - Applies hot-reload changes via ReloadHandlerRegistry
  - Notifies Restart Orchestrator when restart-required keys change
  - Caches active configuration in memory
  - Exposes current config to the service
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Optional, Type

import consul
from pydantic import BaseModel

from shared.config_lib.reload_handlers import ReloadHandlerRegistry
from shared.config_lib.restart_handlers import RestartNotifier
from shared.config_lib.schema import (
    GlobalConfig,
    is_restart_required,
)
from shared.config_lib.validator import diff_config, validate_config

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Central config manager for any service.

    Usage:
        mgr = ConfigManager(service_name="ai-service-a")
        mgr.start()   # loads initial config + starts background watcher
        cfg = mgr.get_config()  # returns current Pydantic model
        mgr.reload_registry.register("thresholds.confidence", my_handler)
        ...
        mgr.stop()  # on graceful shutdown
    """

    def __init__(
        self,
        service_name: str,
        consul_host: str | None = None,
        consul_port: int | None = None,
    ) -> None:
        self._service_name = service_name
        self._consul_host = consul_host or os.environ.get("CONSUL_HOST", "consul")
        self._consul_port = consul_port or int(os.environ.get("CONSUL_PORT", "8500"))
        self._consul: Optional[consul.Consul] = None

        # Current config state
        self._config: Optional[BaseModel] = None
        self._global_config: Optional[GlobalConfig] = None
        self._config_version: int = 0
        self._lock = threading.RLock()

        # Handler registries
        self.reload_registry = ReloadHandlerRegistry()
        self._restart_notifier: Optional[RestartNotifier] = None

        # Watcher thread
        self._watcher_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Connect to Consul, load initial config, start background watcher."""
        self._connect()
        self._restart_notifier = RestartNotifier(self._consul, self._service_name)

        # Load initial config
        self._load_initial_config()

        # Start background watcher thread (blocking queries)
        self._watcher_thread = threading.Thread(
            target=self._watch_loop,
            name=f"config-watcher-{self._service_name}",
            daemon=True,
        )
        self._watcher_thread.start()
        logger.info(
            "config_manager.started",
            extra={"service": self._service_name, "consul": f"{self._consul_host}:{self._consul_port}"},
        )

    def stop(self) -> None:
        """Stop the background watcher. Call during graceful shutdown."""
        self._stop_event.set()
        if self._watcher_thread and self._watcher_thread.is_alive():
            self._watcher_thread.join(timeout=5)
        logger.info("config_manager.stopped", extra={"service": self._service_name})

    def get_config(self) -> BaseModel | None:
        """Returns the current validated service config (thread-safe)."""
        with self._lock:
            return self._config

    def get_global_config(self) -> GlobalConfig | None:
        """Returns the current global config (thread-safe)."""
        with self._lock:
            return self._global_config

    def get_version(self) -> int:
        """Returns the current config version."""
        return self._config_version

    def is_maintenance_mode(self) -> bool:
        """Check if the platform is in maintenance mode."""
        gc = self.get_global_config()
        return gc.maintenance_mode if gc else False

    # ------------------------------------------------------------------
    # Consul connection
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """Establish connection to Consul agent."""
        max_retries = 10
        for attempt in range(max_retries):
            try:
                self._consul = consul.Consul(
                    host=self._consul_host,
                    port=self._consul_port,
                )
                # Verify connectivity
                self._consul.status.leader()
                logger.info("config_manager.consul_connected")
                return
            except Exception as exc:
                if attempt == max_retries - 1:
                    logger.critical(
                        "config_manager.consul_connect_failed",
                        extra={"error": str(exc), "attempts": max_retries},
                    )
                    raise
                wait = min(2 ** attempt, 30)
                logger.warning(
                    "config_manager.consul_retry",
                    extra={"attempt": attempt + 1, "wait": wait},
                )
                time.sleep(wait)

    # ------------------------------------------------------------------
    # Initial load
    # ------------------------------------------------------------------

    def _load_initial_config(self) -> None:
        """Load config from Consul KV at startup."""
        # Load global config
        global_raw = self._read_kv("config/global")
        if global_raw:
            gc = validate_config("global", global_raw)
            if gc:
                with self._lock:
                    self._global_config = gc

        # Load service-specific config
        svc_raw = self._read_kv(f"config/{self._service_name}")
        if svc_raw:
            cfg = validate_config(self._service_name, svc_raw)
            if cfg:
                with self._lock:
                    self._config = cfg
                    self._config_version = svc_raw.get("_version", 1)
                logger.info(
                    "config_manager.initial_load_ok",
                    extra={"service": self._service_name, "version": self._config_version},
                )
            else:
                logger.warning("config_manager.initial_config_invalid_using_defaults")
                self._apply_defaults()
        else:
            logger.warning("config_manager.no_consul_config_using_defaults")
            self._apply_defaults()

    def _apply_defaults(self) -> None:
        """Apply default config when Consul has no data yet."""
        default = validate_config(self._service_name, {})
        with self._lock:
            self._config = default
            self._config_version = 0

    # ------------------------------------------------------------------
    # Consul KV read
    # ------------------------------------------------------------------

    def _read_kv(self, key: str) -> dict[str, Any] | None:
        """Read a JSON value from Consul KV."""
        try:
            index, data = self._consul.kv.get(key)
            if data is None or data.get("Value") is None:
                return None
            return json.loads(data["Value"].decode("utf-8"))
        except Exception as exc:
            logger.error("config_manager.kv_read_error", extra={"key": key, "error": str(exc)})
            return None

    def _read_kv_with_index(self, key: str, index: int = 0) -> tuple[int, dict | None]:
        """Blocking read from Consul KV. Returns (new_index, value)."""
        try:
            new_index, data = self._consul.kv.get(key, index=str(index), wait="30s")
            if data is None or data.get("Value") is None:
                return new_index or 0, None
            val = json.loads(data["Value"].decode("utf-8"))
            return new_index or 0, val
        except Exception as exc:
            logger.error("config_manager.kv_blocking_read_error", extra={"key": key, "error": str(exc)})
            return index, None

    # ------------------------------------------------------------------
    # Background watcher (blocking queries)
    # ------------------------------------------------------------------

    def _watch_loop(self) -> None:
        """
        Continuously watches Consul KV using blocking queries.
        When a change is detected, validates and applies it.
        """
        svc_key = f"config/{self._service_name}"
        last_index = 0

        while not self._stop_event.is_set():
            try:
                new_index, raw = self._read_kv_with_index(svc_key, last_index)

                # No change or same index — loop again
                if new_index == last_index or raw is None:
                    last_index = new_index
                    continue

                last_index = new_index
                self._handle_config_update(raw)

            except Exception as exc:
                logger.error("config_manager.watch_error", extra={"error": str(exc)})
                # Backoff on error before retrying
                if not self._stop_event.wait(5):
                    continue

    def _handle_config_update(self, raw: dict[str, Any]) -> None:
        """Process an incoming config update from Consul."""
        # Check version — ignore duplicate/stale updates
        new_version = raw.get("_version", 0)
        if new_version <= self._config_version:
            logger.debug("config_manager.stale_version_ignored", extra={"version": new_version})
            return

        # Validate
        new_config = validate_config(self._service_name, raw)
        if new_config is None:
            logger.error("config_manager.update_rejected_invalid")
            return

        # Diff against current config
        old_config = self.get_config()
        if old_config is not None:
            changed_keys = diff_config(old_config, new_config)
        else:
            changed_keys = set(raw.keys())

        if not changed_keys:
            logger.debug("config_manager.no_effective_changes")
            with self._lock:
                self._config_version = new_version
            return

        # Check if any changes require restart
        restart_keys = {k for k in changed_keys if is_restart_required(self._service_name, {k})}
        hot_keys = changed_keys - restart_keys

        # Apply hot-reload changes immediately
        if hot_keys and old_config:
            old_dict = old_config.model_dump()
            new_dict = new_config.model_dump()
            hot_changes = {}
            for k in hot_keys:
                old_val = _nested_get(old_dict, k)
                new_val = _nested_get(new_dict, k)
                hot_changes[k] = (old_val, new_val)
            fired = self.reload_registry.fire(hot_changes)
            logger.info(
                "config_manager.hot_reload_applied",
                extra={"keys": sorted(hot_keys), "handlers_fired": fired},
            )

        # Update cached config
        with self._lock:
            self._config = new_config
            self._config_version = new_version

        # Signal restart orchestrator if needed
        if restart_keys and self._restart_notifier:
            self._restart_notifier.notify_restart_required(restart_keys, new_version)
            logger.warning(
                "config_manager.restart_required_signaled",
                extra={"keys": sorted(restart_keys), "version": new_version},
            )

        logger.info(
            "config_manager.config_updated",
            extra={
                "version": new_version,
                "hot_keys": sorted(hot_keys),
                "restart_keys": sorted(restart_keys),
            },
        )


def _nested_get(d: dict, dotted_key: str) -> Any:
    """Get a value from a nested dict using dotted key path."""
    keys = dotted_key.split(".")
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        else:
            return None
    return d

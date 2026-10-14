"""
restart_handlers.py — Notifies the restart orchestrator when restart-required settings change.

When a RESTART-REQUIRED config key changes, the service does NOT restart itself.
Instead, it writes a restart request to Consul KV under config/restart-required/{service}/,
and the central Restart Orchestrator picks it up.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class RestartNotifier:
    """
    Writes restart-required signals to Consul KV.
    The Restart Orchestrator watches these keys and coordinates rolling restarts.
    """

    def __init__(self, consul_client: Any, service_name: str) -> None:
        self._consul = consul_client
        self._service_name = service_name

    def notify_restart_required(self, changed_keys: set[str], config_version: int) -> bool:
        """
        Write a restart request to Consul KV.

        Key: config/restart-required/{service_name}
        Value: JSON with changed_keys, config_version, timestamp.

        Returns True if the write succeeded.
        """
        key = f"config/restart-required/{self._service_name}"
        payload = {
            "service": self._service_name,
            "changed_keys": sorted(changed_keys),
            "config_version": config_version,
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }

        try:
            self._consul.kv.put(key, json.dumps(payload))
            logger.warning(
                "restart_notifier.restart_requested",
                extra={
                    "service": self._service_name,
                    "changed_keys": sorted(changed_keys),
                    "config_version": config_version,
                },
            )
            return True
        except Exception as exc:
            logger.error(
                "restart_notifier.write_failed",
                extra={"service": self._service_name, "error": str(exc)},
            )
            return False

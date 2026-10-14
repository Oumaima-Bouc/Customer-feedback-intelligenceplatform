"""
Restart Orchestrator — Central rolling-restart coordinator.

Responsibilities:
  - Watches Consul KV config/restart-required/{service}/ for pending restart requests
  - Deduplicates and debounces rapid updates (10s window)
  - Coordinates ROLLING restarts — NEVER simultaneous
  - Uses Docker Engine API (Python SDK) — NOT shell subprocess
  - Waits for health check verification after each restart
  - Exposes /health endpoint
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import consul
import docker
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from shared.logging_lib.setup import configure_service_logging

# ---------------------------------------------------------------------------
# Logging — must be configured before any log output
# ---------------------------------------------------------------------------
configure_service_logging(
    service_name=os.environ.get("SERVICE_NAME", "restart-orchestrator"),
    log_level=os.environ.get("LOG_LEVEL", "INFO"),
    log_format="json",
    log_dir="/logs",
    enable_file_logging=True,
    enable_secret_redaction=True,
)

logger = structlog.get_logger(__name__)

app = FastAPI(title="Restart Orchestrator", version="1.0.0")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CONSUL_HOST = os.environ.get("CONSUL_HOST", "consul")
CONSUL_PORT = int(os.environ.get("CONSUL_PORT", "8500"))
DEBOUNCE_SECONDS = 10  # Wait this long before acting on a restart request
HEALTH_CHECK_TIMEOUT = 120  # Max seconds to wait for healthy after restart
HEALTH_CHECK_INTERVAL = 5  # Seconds between health polls

# Service → container name mapping (from docker-compose labels)
MANAGED_SERVICES = {
    "ai-service-a": "ai-service-a",
    "ai-service-b": "ai-service-b",
    "reply-service": "reply-service",
    "feedback-service": "feedback-service",
}

# Rolling restart order — NEVER restart all simultaneously
RESTART_ORDER = ["ai-service-a", "ai-service-b", "reply-service", "feedback-service"]

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_restart_lock = threading.Lock()
_last_restart: dict[str, float] = {}
_pending_restarts: dict[str, dict] = {}
_restart_history: list[dict] = []


# ---------------------------------------------------------------------------
# Docker SDK client
# ---------------------------------------------------------------------------
def get_docker_client() -> docker.DockerClient:
    """Connect to Docker Engine API via mounted socket."""
    return docker.DockerClient(base_url="unix:///var/run/docker.sock")


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    checks = {"alive": True}
    # Consul check
    try:
        c = consul.Consul(host=CONSUL_HOST, port=CONSUL_PORT)
        c.status.leader()
        checks["consul_connected"] = True
    except Exception:
        checks["consul_connected"] = False
    # Docker check
    try:
        client = get_docker_client()
        client.ping()
        checks["docker_connected"] = True
        client.close()
    except Exception:
        checks["docker_connected"] = False

    all_ok = all(checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "healthy" if all_ok else "degraded", "checks": checks},
    )


# ---------------------------------------------------------------------------
# Restart status
# ---------------------------------------------------------------------------
@app.get("/api/restart/status")
async def restart_status():
    """Current pending restarts + history."""
    return {
        "pending": _pending_restarts,
        "history": _restart_history[-20:],  # Last 20 restarts
    }


@app.post("/api/restart/{service_name}")
async def manual_restart(service_name: str):
    """Manually trigger a rolling restart for a service."""
    if service_name not in MANAGED_SERVICES:
        raise HTTPException(404, f"Unknown service: {service_name}")

    result = _perform_restart(service_name, reason="manual_trigger")
    return result


# ---------------------------------------------------------------------------
# Rolling restart logic (Docker SDK)
# ---------------------------------------------------------------------------
def _perform_restart(service_name: str, reason: str = "config_change") -> dict:
    """
    Perform a graceful restart of a single service container.
    Uses Docker SDK — NOT shell subprocess.
    """
    container_name = MANAGED_SERVICES.get(service_name)
    if not container_name:
        return {"error": f"Unknown service: {service_name}"}

    with _restart_lock:
        # Debounce: skip if restarted too recently
        last = _last_restart.get(service_name, 0)
        if time.time() - last < DEBOUNCE_SECONDS:
            logger.info(
                "restart.debounced",
                extra={"service": service_name, "seconds_since_last": time.time() - last},
            )
            return {"status": "debounced", "service": service_name}

        try:
            client = get_docker_client()

            # Find container
            try:
                container = client.containers.get(container_name)
            except docker.errors.NotFound:
                return {"error": f"Container {container_name} not found"}

            logger.warning(
                "restart.starting",
                extra={"service": service_name, "container": container_name, "reason": reason},
            )

            # Graceful restart (sends SIGTERM, waits, then SIGKILL)
            container.restart(timeout=30)

            # Wait for health check
            healthy = _wait_for_healthy(client, container_name)

            _last_restart[service_name] = time.time()

            result = {
                "status": "restarted" if healthy else "restarted_unhealthy",
                "service": service_name,
                "container": container_name,
                "reason": reason,
                "healthy": healthy,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            _restart_history.append(result)

            # Clear restart-required flag in Consul
            if healthy:
                _clear_restart_flag(service_name)

            client.close()
            return result

        except Exception as exc:
            logger.error("restart.failed", extra={"service": service_name, "error": str(exc)})
            result = {
                "status": "failed",
                "service": service_name,
                "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _restart_history.append(result)
            return result


def _wait_for_healthy(client: docker.DockerClient, container_name: str) -> bool:
    """Poll container health status until healthy or timeout."""
    start = time.time()
    while time.time() - start < HEALTH_CHECK_TIMEOUT:
        try:
            container = client.containers.get(container_name)
            state = container.attrs.get("State", {})
            health = state.get("Health", {})
            status = health.get("Status", "unknown")

            if status == "healthy":
                logger.info("restart.health_ok", extra={"container": container_name})
                return True
            elif container.status == "running" and not health:
                # No healthcheck defined — assume healthy after 10s running
                if time.time() - start > 10:
                    return True
        except Exception:
            pass

        time.sleep(HEALTH_CHECK_INTERVAL)

    logger.error("restart.health_timeout", extra={"container": container_name})
    return False


def _clear_restart_flag(service_name: str) -> None:
    """Clear the restart-required flag in Consul after successful restart."""
    try:
        c = consul.Consul(host=CONSUL_HOST, port=CONSUL_PORT)
        key = f"config/restart-required/{service_name}"
        payload = json.dumps({"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()})
        c.kv.put(key, payload)
    except Exception as exc:
        logger.error("restart.clear_flag_failed", extra={"service": service_name, "error": str(exc)})


# ---------------------------------------------------------------------------
# Background Consul watcher — watches restart-required keys
# ---------------------------------------------------------------------------
def _consul_watcher():
    """
    Background thread that watches Consul KV for restart-required signals.
    Uses blocking queries — NOT polling loops.
    """
    c = consul.Consul(host=CONSUL_HOST, port=CONSUL_PORT)
    last_indices: dict[str, int] = {svc: 0 for svc in MANAGED_SERVICES}

    while True:
        for service_name in RESTART_ORDER:
            key = f"config/restart-required/{service_name}"
            try:
                new_index, data = c.kv.get(key, index=str(last_indices[service_name]), wait="10s")

                if new_index == last_indices[service_name]:
                    continue

                last_indices[service_name] = new_index or 0

                if data is None or data.get("Value") is None:
                    continue

                payload = json.loads(data["Value"].decode("utf-8"))
                status = payload.get("status", "none")

                if status == "pending":
                    logger.info(
                        "watcher.restart_pending",
                        extra={"service": service_name, "payload": payload},
                    )

                    # Debounce: wait before acting
                    time.sleep(DEBOUNCE_SECONDS)

                    # Perform rolling restart
                    _perform_restart(service_name, reason="config_change")

                    # IMPORTANT: rolling restart — wait between services
                    time.sleep(5)

            except Exception as exc:
                logger.error("watcher.error", extra={"service": service_name, "error": str(exc)})
                time.sleep(5)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    """Start the Consul watcher in a background thread."""
    watcher = threading.Thread(target=_consul_watcher, name="restart-watcher", daemon=True)
    watcher.start()
    logger.info("restart_orchestrator.started")

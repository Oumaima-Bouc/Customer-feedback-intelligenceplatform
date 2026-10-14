"""
Manual "Run Now" orchestration for the full pipeline (header button).

Flow (background thread, non-blocking):
  scrape (ai-service-b)  ->  wait for scrape to finish  ->  pipeline (ai-service-a)
  ->  invalidate the dashboard recompute cache so the freshly-processed data shows.

Design decisions (confirmed with the operator):
  - Reject if a run is already in progress — scheduled OR manual — detected from
    job_executions plus this orchestrator's own state. Never overlapping runs.
  - Asynchronous: the POST returns immediately; the frontend polls get_status().
  - The automatic schedule is left untouched — this is just an extra, idempotent run
    (only new/unclassified comments are processed; human corrections stay protected).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from typing import Any, Dict, Optional

from config.database import get_conn
from shared.utils.date_helper import utc_now_iso
from modules.dashboard import dashboard_service

log = logging.getLogger("dashboard.system")

_AI_A_URL = os.environ.get("AI_SERVICE_A_URL", "http://ai-service-a:8080")
_AI_B_URL = os.environ.get("AI_SERVICE_B_URL", "http://ai-service-b:8081")
_ADMIN_API_KEY = os.environ.get("DASHBOARD_API_KEY", "")

_SCRAPE_APPEAR_GRACE_S = 30        # how long to wait for a scrape run to register
_SCRAPE_WAIT_TIMEOUT_S = 900       # max wait for scraping to finish (15 min)
_PIPELINE_TIMEOUT_S = 1800         # max time to hold the pipeline call (30 min)
_POLL_INTERVAL_S = 4

_RUN_JOBS = ("fb_scraper", "ml_pipeline")

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "phase": "idle",       # idle | scraping | analyzing | done | failed
    "started_at": None,
    "finished_at": None,
    "error": None,
    "triggered_by": None,
}


# ── helpers ───────────────────────────────────────────────────────────────────
def _count_running(job_name: Optional[str] = None) -> int:
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if job_name:
                cur.execute("SELECT COUNT(*) FROM job_executions WHERE status='running' AND job_name=%s", (job_name,))
            else:
                cur.execute("SELECT COUNT(*) FROM job_executions WHERE status='running' AND job_name = ANY(%s)", (list(_RUN_JOBS),))
            return cur.fetchone()[0]
    except Exception:
        return 0


def _post(url: str, payload: dict, headers: Optional[dict] = None, timeout: int = 25) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        if v:
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode() or "{}"
        return json.loads(body) if body.strip().startswith("{") else {"raw": body}


def _set_phase(phase: str) -> None:
    with _lock:
        _state["phase"] = phase


def _finish(error: Optional[str]) -> None:
    with _lock:
        _state["phase"] = "failed" if error else "done"
        _state["finished_at"] = utc_now_iso()
        _state["error"] = error


def _wait_for_job(job_name: str, timeout_s: int) -> None:
    """Wait until a run of `job_name` has appeared and then cleared. If it never
    appears within the grace window (e.g. nothing to do) we proceed."""
    deadline = time.time() + timeout_s
    grace = time.time() + _SCRAPE_APPEAR_GRACE_S
    appeared = False
    while time.time() < deadline:
        running = _count_running(job_name)
        if running > 0:
            appeared = True
        elif appeared:
            return                      # was running, now done
        elif time.time() > grace:
            return                      # never started — proceed
        time.sleep(_POLL_INTERVAL_S)


def _orchestrate() -> None:
    try:
        log.info("system_run.scrape_trigger")
        _post(f"{_AI_B_URL}/internal/scrape/run", {}, timeout=25)
        _wait_for_job("fb_scraper", _SCRAPE_WAIT_TIMEOUT_S)

        _set_phase("analyzing")
        log.info("system_run.pipeline_trigger")
        _post(f"{_AI_A_URL}/internal/pipeline/run", {}, timeout=30)
        _wait_for_job("ml_pipeline", _PIPELINE_TIMEOUT_S)

        # Surface the freshly-processed data on the next dashboard read.
        dashboard_service.invalidate_cache()
        _finish(None)
        log.info("system_run.complete")
    except Exception as exc:  # noqa: BLE001 — report any failure back to the UI
        log.error("system_run.failed: %s", exc)
        _finish(str(exc))


# ── public API ─────────────────────────────────────────────────────────────────
def is_busy() -> bool:
    with _lock:
        if _state["phase"] in ("scraping", "analyzing"):
            return True
    return _count_running() > 0


def get_status() -> Dict[str, Any]:
    with _lock:
        state = dict(_state)
    state["running"] = state["phase"] in ("scraping", "analyzing") or _count_running() > 0
    return state


def trigger_run(triggered_by: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Start a full run. Returns None if a run is already in progress (-> 409)."""
    with _lock:
        if _state["phase"] in ("scraping", "analyzing"):
            return None
        if _count_running() > 0:
            return None
        _state.update({
            "phase": "scraping",
            "started_at": utc_now_iso(),
            "finished_at": None,
            "error": None,
            "triggered_by": triggered_by,
        })
    threading.Thread(target=_orchestrate, name="system-run", daemon=True).start()
    return {"status": "started", "phase": "scraping"}

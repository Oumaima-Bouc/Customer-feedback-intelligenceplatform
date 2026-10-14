"""
Connection Manager — source onboarding & health.

Responsibilities:
  - validate_connection(): live Meta Graph API test of a page/profile + its
    real public name (used when a new source is added or re-tested).
  - Synchronous DB helpers (psycopg2) for source health/name and the
    scraping_job_instances tracking table.

Why psycopg2 (sync) here instead of the asyncpg pool: these helpers are called
from the FastAPI health-server thread, which runs a *different* event loop than
the one that owns the asyncpg pool. asyncpg pools are bound to the loop that
created them, so we use short-lived psycopg2 connections (loop-agnostic) for
control-plane operations. They are always invoked via asyncio.to_thread().
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import aiohttp
import psycopg2
import structlog

from config import settings
from db.connection import _build_dsn
from shared.meta_graph import derive_permissions

log = structlog.get_logger(__name__)

# Sentinel: distinguishes "leave column untouched" from "set to NULL" in updates.
_UNSET: Any = object()


# ---------------------------------------------------------------------------
# Live Meta Graph API connection test
# ---------------------------------------------------------------------------
def _friendly_error(code: Optional[int], message: str) -> str:
    """Map raw Meta error codes to operator-friendly messages."""
    if code == 190:
        return "Access token is invalid or expired."
    if code in (100, 803):
        return "Page/profile not found, or not accessible with this token."
    if code in (200, 10, 3):
        return "This token does not have permission to read this page/profile."
    if code == 368:
        return "This resource is temporarily blocked by Meta. Try again later."
    return f"Meta API error {code}: {message}" if code else (message or "Unknown Meta API error.")


async def _debug_token_scopes(session, token: str) -> Optional[list]:
    """
    Return the token's granted scopes via debug_token (self-introspection), or None
    if unavailable. This is the reliable capability signal for a Page access token
    (page tokens can't read `tasks` on the page node or use /me/permissions).
    """
    url = f"{settings.graph_base_url}/debug_token"
    params = {"input_token": token, "access_token": token}
    try:
        async with session.get(url, params=params) as resp:
            data = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.info("connection.debug_token.network_error", error=str(exc))
        return None
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("scopes"), list):
            return inner["scopes"]
        log.info("connection.debug_token.no_scopes", detail=str(data.get("error") or "no scopes")[:200])
    return None


async def _probe_scrape(session, external_id: str, token: str, platform: str) -> bool:
    """
    Behavioral, read-only test of comment-read access: read one item from the
    page feed (Facebook) or media (Instagram). Empty data on a 200 still counts
    as success (a page may simply have no posts). Any Meta error => not granted.
    """
    edge = "media" if platform == "instagram" else "feed"
    url = f"{settings.graph_base_url}/{external_id}/{edge}"
    params = {"fields": "id", "limit": 1, "access_token": token}
    try:
        async with session.get(url, params=params) as resp:
            data = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        log.info("connection.scrape_probe.network_error", external_id=external_id, error=str(exc))
        return False
    if not isinstance(data, dict) or data.get("error"):
        code = (data.get("error") or {}).get("code") if isinstance(data, dict) else None
        log.info("connection.scrape_probe.denied", external_id=external_id, code=code)
        return False
    return "data" in data


async def validate_connection(
    platform: str,
    external_id: str,
    access_token: str,
) -> dict[str, Any]:
    """
    Live-validate a page/profile connection and detect its capabilities.

    Returns:
        {"ok": bool, "name": str|None, "external_id": str|None,
         "error": str|None, "error_code": int|None,
         "can_scrape": bool, "can_reply": bool,
         "scrape_reason": str|None, "reply_reason": str|None}

    `ok` means the token is valid and the page resolved (we got an identity+name).
    `can_scrape` is a real behavioral probe of comment-read; `can_reply` is derived
    from the page `tasks`. Reasons explain any missing permission for the operator.
    """
    token = (access_token or "").strip() or settings.meta_access_token
    # NOTE: do NOT request `tasks` — it is not a valid field on the page node for a
    # Page access token and makes the whole call fail with code 100. Capabilities
    # come from the token's granted scopes (debug_token) instead.
    fields = "id,name,username" if platform == "instagram" else "id,name"
    url = f"{settings.graph_base_url}/{external_id}"
    params = {"fields": fields, "access_token": token}
    timeout = aiohttp.ClientTimeout(total=20, connect=10)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # ── Call 1: identity + tasks ──
            try:
                async with session.get(url, params=params) as resp:
                    data = await resp.json(content_type=None)
            except Exception as exc:  # noqa: BLE001 — network/timeout/JSON failure
                log.warning("connection.validate.network_error", external_id=external_id, error=str(exc))
                return {"ok": False, "name": None, "external_id": None,
                        "error": f"Could not reach the Meta Graph API ({exc}).", "error_code": None}

            if not isinstance(data, dict):
                return {"ok": False, "name": None, "external_id": None,
                        "error": "Unexpected response from Meta Graph API.", "error_code": None}

            error = data.get("error")
            if error:
                code = error.get("code")
                msg = error.get("message", "")
                log.info("connection.validate.meta_error", external_id=external_id, code=code, msg=msg)
                return {"ok": False, "name": None, "external_id": None,
                        "error": _friendly_error(code, msg), "error_code": code}

            resolved_id = data.get("id")
            if not resolved_id:
                return {"ok": False, "name": None, "external_id": None,
                        "error": "Page/profile not found or not accessible with this token.",
                        "error_code": None}

            name = data.get("name") or data.get("username") or str(resolved_id)

            # ── Capabilities ──
            if platform == "instagram":
                # IG: behavioral media probe; replies unsupported (base spec Missing #8).
                scopes = None
                feed_ok = await _probe_scrape(session, external_id, token, platform)
            else:
                # Facebook page token: granted scopes are the reliable signal.
                # Fall back to a behavioral feed probe only if debug_token is unavailable.
                scopes = await _debug_token_scopes(session, token)
                feed_ok = None
                if scopes is None:
                    feed_ok = await _probe_scrape(session, external_id, token, platform)
    except Exception as exc:  # noqa: BLE001 — session-level failure
        log.warning("connection.validate.session_error", external_id=external_id, error=str(exc))
        return {"ok": False, "name": None, "external_id": None,
                "error": f"Could not reach the Meta Graph API ({exc}).", "error_code": None}

    can_scrape, can_reply, scrape_reason, reply_reason = derive_permissions(scopes, feed_ok)
    # Instagram replies are not supported yet (base spec Missing #8).
    if platform == "instagram":
        can_reply = False
        reply_reason = "Replies are not supported for Instagram sources yet."

    log.info(
        "connection.validate.ok",
        external_id=external_id, name=name, can_scrape=can_scrape, can_reply=can_reply,
    )
    return {
        "ok": True, "name": name, "external_id": str(resolved_id),
        "error": None, "error_code": None,
        "can_scrape": can_scrape, "can_reply": can_reply,
        "scrape_reason": scrape_reason, "reply_reason": reply_reason,
    }


# ---------------------------------------------------------------------------
# Synchronous DB helpers (psycopg2) — safe to call from any thread/loop
# ---------------------------------------------------------------------------
def _sync_dsn() -> str:
    return _build_dsn().replace("postgresql+asyncpg://", "postgresql://")


def get_source_sync(source_id: int) -> Optional[dict]:
    """Load a single source row. Returns None if it does not exist."""
    conn = psycopg2.connect(_sync_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, platform, external_id, name, access_token, is_active, health_status "
                "FROM scraping_sources WHERE id = %s",
                (source_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "id": row[0], "platform": row[1], "external_id": row[2], "name": row[3],
        "access_token": row[4], "is_active": row[5], "health_status": row[6],
    }


def update_source_health_sync(
    source_id: int,
    name: Optional[str] = None,
    health_status: Optional[str] = None,
    last_error: Any = _UNSET,
    can_reply: Optional[bool] = None,
    reply_perm_error: Any = _UNSET,
) -> None:
    """
    Update a source's name / health_status / last_error / can_reply / reply_perm_error.

    Only provided fields are written. For `last_error` and `reply_perm_error`, pass
    None explicitly to CLEAR the column (e.g. on a now-healthy refresh); omit them
    (leave the _UNSET sentinel) to leave the column untouched.
    """
    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        sets.append("name = %s")
        params.append(name)
    if health_status is not None:
        sets.append("health_status = %s")
        params.append(health_status)
    if last_error is not _UNSET:
        sets.append("last_error = %s")
        sets.append("last_error_at = NOW()")
        params.append(last_error)
    if can_reply is not None:
        sets.append("can_reply = %s")
        sets.append("reply_perm_checked_at = NOW()")
        params.append(can_reply)
    if reply_perm_error is not _UNSET:
        sets.append("reply_perm_error = %s")
        params.append(reply_perm_error)
    if not sets:
        return
    sets.append("updated_at = NOW()")
    params.append(source_id)

    conn = psycopg2.connect(_sync_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE scraping_sources SET {', '.join(sets)} WHERE id = %s", params)
        conn.commit()
    finally:
        conn.close()


def upsert_job_instance_sync(
    source_id: int,
    job_name: str,
    next_run_time: Optional[datetime],
    is_enabled: bool = True,
    status: str = "idle",
) -> None:
    """Create or update the scraping_job_instances row for a scheduled job."""
    conn = psycopg2.connect(_sync_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scraping_job_instances
                    (source_id, job_name, status, next_run_time, is_enabled, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (job_name) DO UPDATE SET
                    status = EXCLUDED.status,
                    next_run_time = EXCLUDED.next_run_time,
                    is_enabled = EXCLUDED.is_enabled,
                    source_id = EXCLUDED.source_id
                """,
                (source_id, job_name, status, next_run_time, is_enabled),
            )
        conn.commit()
    finally:
        conn.close()


def publish_page_usage_sync(source_id: int, quota_pct: float) -> None:
    """
    Publish this page's latest observed X-App-Usage to page_rate_state for the
    reply dispatcher's scrape/reply coordination (partial close of base-spec
    Missing #10). `quota_pct` is the RateGuard fraction (0-1); stored as a
    percentage (0-100) to match the reply usage ceiling. Best-effort.
    """
    conn = psycopg2.connect(_sync_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO page_rate_state (source_id, app_usage_pct, observed_at) "
                "VALUES (%s, %s, NOW()) "
                "ON CONFLICT (source_id) DO UPDATE SET "
                "app_usage_pct = EXCLUDED.app_usage_pct, observed_at = EXCLUDED.observed_at",
                (source_id, round((quota_pct or 0.0) * 100, 2)),
            )
        conn.commit()
    finally:
        conn.close()


def set_job_instance_status_sync(
    job_name: str,
    status: Optional[str] = None,
    is_enabled: Optional[bool] = None,
    mark_run: bool = False,
) -> None:
    """Update status / is_enabled / last_run_at for a job instance (best-effort)."""
    sets: list[str] = []
    params: list[Any] = []
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if is_enabled is not None:
        sets.append("is_enabled = %s")
        params.append(is_enabled)
    if mark_run:
        sets.append("last_run_at = NOW()")
    if not sets:
        return
    params.append(job_name)

    conn = psycopg2.connect(_sync_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE scraping_job_instances SET {', '.join(sets)} WHERE job_name = %s", params)
        conn.commit()
    finally:
        conn.close()

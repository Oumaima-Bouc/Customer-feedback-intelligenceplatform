from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from config.database import get_conn
from infrastructure.consul.consul_client import consul_client
from infrastructure.consul.consul_keys import ConsulKeys
from middleware.error_middleware import NotFoundError, ValidationError
from shared.utils.date_helper import to_iso, compute_next_cron_runs

# Base URL of the scraper service (ai-service-b) on the internal docker network.
_SCRAPER_BASE_URL = os.environ.get("AI_SERVICE_B_URL", "http://ai-service-b:8081")


def _call_scraper(method: str, path: str, payload: Optional[dict] = None, timeout: int = 25) -> dict:
    """
    Call an ai-service-b control endpoint. Returns the parsed JSON body.

    - On a 4xx/5xx with a JSON body (e.g. a failed connection test), the body is
      returned so the caller can inspect it (it carries an `error` message).
    - On a transport failure (service unreachable), raises ValidationError so the
      operator sees a clear message instead of a 500.
    """
    url = f"{_SCRAPER_BASE_URL}{path}"
    data = json.dumps(payload or {}).encode("utf-8") if method.upper() != "GET" else None
    req = urllib.request.Request(url, data=data, method=method.upper(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {"error": str(parsed)}
        parsed.setdefault("_http_status", exc.code)
        return parsed
    except Exception as exc:  # URLError / timeout / connection refused
        raise ValidationError(f"Scraper service is unavailable: {exc}")

def get_service_config(service_name: str) -> Dict[str, Any]:
    value = consul_client.get(ConsulKeys.service_config(service_name))
    if value is None: raise NotFoundError(f"No config found for {service_name}")
    return {"service": service_name, "config": value}

def update_service_config(service_name: str, new_settings: dict) -> Dict[str, Any]:
    from shared.config_lib.schema import is_restart_required
    from shared.config_lib.validator import validate_config, diff_config
    key = ConsulKeys.service_config(service_name)
    existing = consul_client.get(key) or {}
    current_version = existing.get("_version", 0)
    new_payload = _deep_merge(existing, new_settings)
    new_payload["_version"] = current_version + 1
    validated = validate_config(service_name, new_payload)
    if validated is None: raise ValidationError(f"Configuration validation failed for {service_name}")
    restart_warnings: List[str] = []
    if existing:
        old_validated = validate_config(service_name, existing)
        if old_validated:
            changed = diff_config(old_validated, validated)
            restart_keys = {k for k in changed if is_restart_required(service_name, {k})}
            restart_warnings = sorted(restart_keys)
    consul_client.put(key, new_payload)
    if restart_warnings:
        _request_service_restart(service_name, restart_warnings, "config_change")
    return {"service": service_name, "version": new_payload["_version"], "status": "published", "restart_required_keys": restart_warnings, "warning": f"Restart required for: {restart_warnings}" if restart_warnings else None}

def _deep_merge(base: dict, patch: dict) -> dict:
    merged = dict(base or {})
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged

def _service_config(service_name: str) -> dict:
    return consul_client.get(ConsulKeys.service_config(service_name)) or {}

def _request_service_restart(service_name: str, changed_keys: list[str], reason: str) -> None:
    consul_client.put(
        ConsulKeys.restart_required(service_name),
        {
            "service": service_name,
            "changed_keys": changed_keys,
            "config_version": (_service_config(service_name).get("_version") or 0),
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "reason": reason,
        },
    )

def get_config_versions() -> Dict[str, Any]:
    versions = {}
    for svc in ["global", "ai-service-a", "ai-service-b"]:
        try:
            cfg = consul_client.get(ConsulKeys.service_config(svc)); versions[svc] = cfg.get("_version", 0) if cfg else None
        except Exception:
            versions[svc] = "error"
    return versions

def get_restart_status() -> Dict[str, Any]:
    results = {}
    for svc in ["ai-service-a", "ai-service-b"]:
        try:
            data = consul_client.get(ConsulKeys.restart_required(svc)); results[svc] = data if data else {"status": "none"}
        except Exception:
            results[svc] = {"status": "error"}
    return results
async def get_all_services_health() -> Dict[str, Any]:
    import aiohttp
    service_urls = {"ai-service-a": "http://ai-service-a:8080/health", "ai-service-b": "http://ai-service-b:8081/health", "restart-orchestrator": "http://restart-orchestrator:8082/health"}
    results = {}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
        for name, url in service_urls.items():
            try:
                async with session.get(url) as resp:
                    data = await resp.json(); results[name] = {"status": data.get("status"), "checks": data.get("checks")}
            except Exception as exc:
                results[name] = {"status": "unreachable", "error": str(exc)}
    return results
# sources

def list_sources():
    with get_conn() as conn:
        cur = conn.cursor(); cur.execute("SELECT id, platform, external_id, name, is_active, health_status, last_scraped_at, total_comments_scraped, last_error, can_reply FROM scraping_sources ORDER BY platform, id"); rows = cur.fetchall()
    def _to_dict(r): return {"id": r[0], "external_id": r[2], "name": r[3], "is_active": r[4], "health_status": r[5], "last_scraped_at": to_iso(r[6]), "total_comments_scraped": r[7], "last_error": r[8], "can_reply": r[9]}
    fb=[r for r in rows if r[1]=="facebook"]; ig=[r for r in rows if r[1]=="instagram"]
    return {"facebook": {"total": len(fb), "max_allowed": 70, "connections": [_to_dict(r) for r in fb]}, "instagram": {"total": len(ig), "max_allowed": 70, "connections": [_to_dict(r) for r in ig]}}

def create_source(platform, external_id, access_token, name=None):
    # 1. Enforce the per-platform limit and reject duplicates up front.
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM scraping_sources WHERE platform = %s", (platform,))
        if cur.fetchone()[0] >= 70:
            raise ValidationError(f"Maximum 70 {platform} sources allowed")
        cur.execute("SELECT id FROM scraping_sources WHERE platform = %s AND external_id = %s", (platform, external_id))
        if cur.fetchone():
            raise ValidationError("This page/profile is already connected.")

    # 2. Live connection test via the scraper service: verifies the page exists,
    #    the token works, and returns the real public name.
    validation = _call_scraper("POST", "/sources/validate", {
        "platform": platform, "external_id": external_id, "access_token": access_token,
    })
    # A hard failure (invalid/expired token, page not found/inaccessible) means we
    # have no page identity — reject creation with the friendly reason.
    if not validation.get("ok"):
        raise ValidationError(validation.get("error") or "Connection test failed. Check the ID and access token.")
    real_name = validation.get("name") or name or external_id
    can_scrape = bool(validation.get("can_scrape", False))
    can_reply = bool(validation.get("can_reply", False))
    scrape_reason = validation.get("scrape_reason")
    reply_reason = validation.get("reply_reason")
    # Healthy ONLY when comment-scrape permission is granted; otherwise the
    # connection is still created but flagged 'error' so the operator can fix + Refresh.
    health = "healthy" if can_scrape else "error"

    # 3. Persist the source with its detected permissions + reasons.
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO scraping_sources "
            "(platform, external_id, name, access_token, is_active, health_status, "
            " can_reply, reply_perm_checked_at, reply_perm_error, last_error, last_error_at) "
            "VALUES (%s, %s, %s, %s, TRUE, %s, %s, NOW(), %s, %s, "
            "        CASE WHEN %s IS NULL THEN NULL ELSE NOW() END) RETURNING id",
            (platform, external_id, real_name, access_token, health,
             can_reply, reply_reason, scrape_reason, scrape_reason),
        )
        new_id = cur.fetchone()[0]

    # 4. Schedule the scrape job ONLY when scraping is permitted. (A non-scrapeable
    #    source stays unscheduled until a later Refresh turns it healthy.)
    next_run_time = None
    scheduled = False
    if can_scrape:
        try:
            sched = _call_scraper("POST", f"/sources/{new_id}/schedule", {})
            scheduled = bool(sched.get("scheduled"))
            next_run_time = sched.get("next_run_time")
        except Exception:
            pass

    return {"id": new_id, "name": real_name, "health_status": health, "status": "created",
            "can_scrape": can_scrape, "can_reply": can_reply,
            "scrape_reason": scrape_reason, "reply_reason": reply_reason,
            "scheduled": scheduled, "next_run_time": next_run_time}

def update_source(source_id, is_active=None, name=None, access_token=None):
    updates=[]; params=[]
    if is_active is not None: updates.append("is_active = %s"); params.append(is_active)
    if name is not None: updates.append("name = %s"); params.append(name)
    if access_token is not None: updates.append("access_token = %s"); params.append(access_token)
    if not updates: raise ValidationError("No fields to update")
    params.append(source_id)
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute(f"UPDATE scraping_sources SET {', '.join(updates)} WHERE id = %s", params)
    # Reflect activation changes in the live scheduler (no restart needed).
    if is_active is True:
        try: _call_scraper("POST", f"/sources/{source_id}/schedule", {})
        except Exception: pass
    elif is_active is False:
        try: _call_scraper("POST", f"/sources/{source_id}/unschedule", {})
        except Exception: pass
    return {"status": "updated", "is_active": is_active}

def delete_source(source_id):
    # Stop the live job first (best-effort), then remove the source and the rows
    # that FK-reference it without ON DELETE CASCADE (active_posts, schedule_state).
    try: _call_scraper("POST", f"/sources/{source_id}/unschedule", {})
    except Exception: pass
    with get_conn() as conn:
        cur=conn.cursor()
        cur.execute("DELETE FROM active_posts WHERE source_id = %s", (source_id,))
        cur.execute("DELETE FROM schedule_state WHERE source_id = %s", (source_id,))
        cur.execute("DELETE FROM scraping_sources WHERE id = %s", (source_id,))
    return {"status": "deleted"}

def refresh_source(source_id):
    """Re-test a source's connection and refresh its public name + permissions/health."""
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute("SELECT id, is_active FROM scraping_sources WHERE id = %s", (source_id,))
        row = cur.fetchone()
        if not row: raise NotFoundError("Source not found")
        is_active = row[1]
    result = _call_scraper("POST", f"/sources/{source_id}/refresh", {})
    # Keep the live scheduler in sync with the (possibly changed) scrape capability.
    try:
        if result.get("ok") and result.get("can_scrape") and is_active:
            _call_scraper("POST", f"/sources/{source_id}/schedule", {})
        else:
            _call_scraper("POST", f"/sources/{source_id}/unschedule", {})
    except Exception:
        pass
    return result

def get_source_health(source_id):
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute("SELECT health_status, last_error, last_error_at, last_scraped_at, total_comments_scraped FROM scraping_sources WHERE id = %s", (source_id,)); row=cur.fetchone()
    if not row: raise NotFoundError("Source not found")
    return {"health_status": row[0], "last_error": row[1], "last_error_at": to_iso(row[2]), "last_scraped_at": to_iso(row[3]), "total_comments_scraped": row[4]}

def get_scraper_settings():
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute("SELECT COUNT(*) FROM scraping_sources WHERE is_active = TRUE"); active_count=cur.fetchone()[0]
    cfg = _service_config("ai-service-b")
    scheduler = cfg.get("scheduler", {})
    interval = int(scheduler.get("scraper_interval_h", 4))
    stagger = int(scheduler.get("scraper_stagger_seconds", 30))
    min_hours=(active_count*stagger)/3600 if active_count else 0
    return {"interval_hours": interval, "stagger_seconds": stagger, "active_sources": active_count, "min_required_interval_hours": round(min_hours, 2), "interval_sufficient": interval >= min_hours}

def update_scraper_settings(data):
    patch = {"scheduler": {}}
    if data.interval_hours is not None:
        patch["scheduler"]["scraper_interval_h"] = data.interval_hours
    if data.stagger_seconds is not None:
        patch["scheduler"]["scraper_stagger_seconds"] = data.stagger_seconds
    if not patch["scheduler"]:
        raise ValidationError("No scraper settings provided")
    return update_service_config("ai-service-b", patch)
# pipeline

def get_pipeline_settings():
    cfg = _service_config("ai-service-a")
    runtime = cfg.get("runtime", {})
    cron = str(runtime.get("schedule_cron", "0 1 * * *"))
    lookback = int(runtime.get("lookback_days", 1))
    run_on_startup = bool(runtime.get("run_on_startup", True))
    return {"pipeline_schedule_cron": cron, "pipeline_lookback_days": lookback, "pipeline_run_on_startup": run_on_startup, "next_run_times": compute_next_cron_runs(cron, 3)}

def update_pipeline_settings(dto):
    patch = {"runtime": {}}
    if dto.schedule_cron is not None:
        patch["runtime"]["schedule_cron"] = dto.schedule_cron
    if dto.lookback_days is not None:
        patch["runtime"]["lookback_days"] = dto.lookback_days
    if dto.run_on_startup is not None:
        patch["runtime"]["run_on_startup"] = dto.run_on_startup
    if not patch["runtime"]:
        raise ValidationError("No pipeline settings provided")
    return update_service_config("ai-service-a", patch)
def validate_cron(cron: str): times=compute_next_cron_runs(cron, 3); return {"valid": bool(times), "next_runs": times} if times else {"valid": False, "error": "Invalid cron expression"}
# word cloud

def get_wordcloud_settings():
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute("SELECT word, frequency, positive_pct, neutral_pct, negative_pct, source, category FROM word_cloud_snapshot ORDER BY frequency DESC"); rows=cur.fetchall()
    curated=[r for r in rows if r[5]=="curated"]; discovered=[r for r in rows if r[5]=="discovered"]
    cfg = _service_config("ai-service-a")
    wc = cfg.get("word_cloud", {})
    return {"settings": {"max_words": int(wc.get("max_words", 200)), "min_frequency": int(wc.get("min_frequency", 3))}, "curated_words": [{"word": r[0], "frequency": r[1], "positive_pct": float(r[2]), "neutral_pct": float(r[3]), "negative_pct": float(r[4]), "category": r[6]} for r in curated], "discovered_words_preview": [{"word": r[0], "frequency": r[1], "positive_pct": float(r[2]), "neutral_pct": float(r[3]), "negative_pct": float(r[4])} for r in discovered[:20]], "total_curated": len(curated), "total_discovered": len(discovered)}

def update_wordcloud_settings(dto):
    patch = {"word_cloud": {}}
    if dto.max_words is not None:
        patch["word_cloud"]["max_words"] = dto.max_words
    if dto.min_frequency is not None:
        patch["word_cloud"]["min_frequency"] = dto.min_frequency
    if not patch["word_cloud"]:
        raise ValidationError("No word-cloud settings provided")
    return update_service_config("ai-service-a", patch)
def add_word(word):
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute("SELECT COUNT(*), SUM(CASE WHEN sentiment='positive' THEN 1 ELSE 0 END), SUM(CASE WHEN sentiment='neutral' THEN 1 ELSE 0 END), SUM(CASE WHEN sentiment='negative' THEN 1 ELSE 0 END) FROM comments WHERE text_content ILIKE %s", (f"%{word}%",)); total, pos, neu, neg=cur.fetchone(); total=total or 0; pos_pct=round((pos or 0)/total*100, 2) if total else 0.0; neu_pct=round((neu or 0)/total*100, 2) if total else 0.0; neg_pct=round((neg or 0)/total*100, 2) if total else 0.0; cur.execute("INSERT INTO word_cloud_snapshot (word, frequency, positive_pct, neutral_pct, negative_pct, source, category) VALUES (%s, %s, %s, %s, %s, 'curated', 'manual') ON CONFLICT (word) DO UPDATE SET frequency = EXCLUDED.frequency, positive_pct = EXCLUDED.positive_pct, neutral_pct = EXCLUDED.neutral_pct, negative_pct = EXCLUDED.negative_pct, source = EXCLUDED.source, category = EXCLUDED.category", (word, total, pos_pct, neu_pct, neg_pct))
    return {"status": "added", "word": word, "frequency": total}
def remove_word(word):
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute("DELETE FROM word_cloud_snapshot WHERE word = %s AND source = 'curated'", (word,))
    return {"status": "removed"}
def hide_word(word):
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute("UPDATE word_cloud_snapshot SET frequency = 0 WHERE word = %s AND source = 'discovered'", (word,))
    return {"status": "hidden"}
# users

def list_users():
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute("SELECT id, username, email, role, is_active, last_login_at, created_at FROM users ORDER BY id"); rows=cur.fetchall()
    return {"users": [{"id": r[0], "username": r[1], "email": r[2], "role": r[3], "is_active": r[4], "last_login_at": to_iso(r[5]), "created_at": to_iso(r[6])} for r in rows]}

def create_user(username, email, password, role):
    from middleware.auth_middleware import hash_password
    if role not in ("admin", "user", "viewer"): raise ValidationError("Invalid role")
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute("INSERT INTO users (username, email, password_hash, role, is_active) VALUES (%s, %s, %s, %s, TRUE) RETURNING id", (username, email, hash_password(password), role)); new_id=cur.fetchone()[0]
    return {"id": new_id, "status": "created"}

def update_user(user_id, role=None, is_active=None, username=None, email=None):
    updates=[]; params=[]
    if username is not None: updates.append("username = %s"); params.append(username)
    if email is not None: updates.append("email = %s"); params.append(email)
    if role is not None: updates.append("role = %s"); params.append(role)
    if is_active is not None: updates.append("is_active = %s"); params.append(is_active)
    if not updates: raise ValidationError("No fields to update")
    params.append(user_id)
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = %s", params)
    return {"status": "updated"}

def delete_user(user_id):
    with get_conn() as conn:
        cur=conn.cursor(); cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    return {"status": "deleted"}

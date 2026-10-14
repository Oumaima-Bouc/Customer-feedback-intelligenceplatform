"""
Health + internal control API for reply-service (mirrors ai-service-b §8.2).

Endpoints:
  GET  /health            — alive + config_loaded + db_connected
  GET  /config            — current Consul config + version
  POST /internal/replies  — enqueue a Group Reply campaign (called by dashboard-backend)

The internal endpoint is guarded by a shared secret header (REPLY_INTERNAL_SECRET)
to proactively avoid base-spec debt #12 (unauthenticated internal control endpoints).
If the secret is unset (local dev), the guard is skipped.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db.connection import check_connection
from enqueue.enqueue_service import create_campaign

logger = logging.getLogger(__name__)

# Set by entrypoint after ConfigManager.start()
config_manager = None
_INTERNAL_SECRET = os.environ.get("REPLY_INTERNAL_SECRET", "")

health_app = FastAPI(title="Reply Service — Group Reply")


@health_app.get("/health")
async def health():
    db_ok = await asyncio.to_thread(check_connection)
    checks = {
        "alive": True,
        "config_loaded": config_manager is not None and config_manager.get_config() is not None,
        "db_connected": db_ok,
    }
    ok = all(checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "healthy" if ok else "degraded", "checks": checks},
    )


@health_app.get("/config")
async def get_config():
    if config_manager is None:
        return {"error": "not initialized"}
    cfg = config_manager.get_config()
    return {"version": config_manager.get_version(), "config": cfg.model_dump() if cfg else None}


class EnqueueRequest(BaseModel):
    reply_text: str
    comment_ids: Optional[list[str]] = None
    filter: Optional[dict] = None
    select_all_matching: bool = False
    created_by: Optional[int] = None


@health_app.post("/internal/replies")
async def internal_replies(req: EnqueueRequest, x_internal_secret: str = Header(default="")):
    if _INTERNAL_SECRET and x_internal_secret != _INTERNAL_SECRET:
        raise HTTPException(status_code=401, detail="Invalid internal secret")
    if not req.reply_text or not req.reply_text.strip():
        raise HTTPException(status_code=400, detail="reply_text is required")
    if not req.select_all_matching and not req.comment_ids and not req.filter:
        raise HTTPException(status_code=400, detail="Provide comment_ids, a filter, or select_all_matching")

    ack = await asyncio.to_thread(
        create_campaign,
        reply_text=req.reply_text.strip(),
        comment_ids=req.comment_ids,
        filter=req.filter,
        select_all_matching=req.select_all_matching,
        created_by=req.created_by,
    )
    return ack

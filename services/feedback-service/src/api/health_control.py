"""
Health + internal control API for feedback-service.

  GET  /health, /config
  POST /internal/feedback        — single correction (capture → registry → overwrite)
  POST /internal/feedback/bulk   — bulk correction (partial success)
  GET  /internal/export          — retraining dataset (JSONL/JSON)

Internal endpoints are guarded by a shared secret (FEEDBACK_INTERNAL_SECRET) to
proactively avoid base-spec debt #12. If unset (local dev), the guard is skipped.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from db.connection import check_connection
from export import training_export
from feedback import feedback_service

logger = logging.getLogger(__name__)

config_manager = None  # set by entrypoint
_INTERNAL_SECRET = os.environ.get("FEEDBACK_INTERNAL_SECRET", "")

health_app = FastAPI(title="Feedback Service — Label Feedback")

_STATUS_HTTP = {"not_found": 404, "locked": 409, "invalid": 400}
_STATUS_DETAIL = {
    "not_found": "Comment not found.",
    "locked": "This comment's labels were already corrected and are locked.",
}


def _guard(secret: str) -> None:
    if _INTERNAL_SECRET and secret != _INTERNAL_SECRET:
        raise HTTPException(status_code=401, detail="Invalid internal secret")


@health_app.get("/health")
async def health():
    db_ok = await asyncio.to_thread(check_connection)
    checks = {
        "alive": True,
        "config_loaded": config_manager is not None and config_manager.get_config() is not None,
        "db_connected": db_ok,
    }
    ok = all(checks.values())
    return JSONResponse(status_code=200 if ok else 503,
                        content={"status": "healthy" if ok else "degraded", "checks": checks})


@health_app.get("/config")
async def get_config():
    if config_manager is None:
        return {"error": "not initialized"}
    cfg = config_manager.get_config()
    return {"version": config_manager.get_version(), "config": cfg.model_dump() if cfg else None}


class FeedbackRequest(BaseModel):
    comment_id: str
    new_topic: Optional[str] = None
    new_sentiment: Optional[str] = None
    user_id: Optional[int] = None


class BulkFeedbackRequest(BaseModel):
    comment_ids: list[str]
    new_topic: Optional[str] = None
    new_sentiment: Optional[str] = None
    user_id: Optional[int] = None


@health_app.post("/internal/feedback")
async def internal_feedback(req: FeedbackRequest, x_internal_secret: str = Header(default="")):
    _guard(x_internal_secret)
    result = await asyncio.to_thread(
        feedback_service.correct, req.comment_id, req.new_topic, req.new_sentiment, req.user_id
    )
    status = result.get("status")
    if status == "ok":
        return {"comment_id": req.comment_id, "effective_topic": result["effective_topic"],
                "effective_sentiment": result["effective_sentiment"], "locked": True}
    code = _STATUS_HTTP.get(status, 500)
    raise HTTPException(status_code=code, detail=result.get("reason") or _STATUS_DETAIL.get(status, "Correction failed."))


@health_app.post("/internal/feedback/bulk")
async def internal_feedback_bulk(req: BulkFeedbackRequest, x_internal_secret: str = Header(default="")):
    _guard(x_internal_secret)
    if not req.comment_ids:
        raise HTTPException(status_code=400, detail="comment_ids is required")
    result = await asyncio.to_thread(
        feedback_service.correct_bulk, req.comment_ids, req.new_topic, req.new_sentiment, req.user_id
    )
    if result.get("status") == "invalid":
        raise HTTPException(status_code=400, detail=result.get("reason") or "Invalid correction.")
    return result


@health_app.get("/internal/export")
async def internal_export(since: str = "", format: str = "jsonl", x_internal_secret: str = Header(default="")):
    _guard(x_internal_secret)
    rows = await asyncio.to_thread(training_export.export_rows, since or None)
    if format == "json":
        return {"total": len(rows), "rows": rows}
    return PlainTextResponse(training_export.to_jsonl(rows), media_type="application/x-ndjson")

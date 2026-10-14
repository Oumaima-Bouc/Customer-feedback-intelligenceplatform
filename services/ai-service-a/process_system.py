"""
process_system.py — Production entry point.

Called as:
    result = process_system(input_data)

Supports three modes:
  - "daily" (default): run the nightly pipeline
  - "reprocess_date_range": reprocess a date range
  - "reprocess_id_range": reprocess an ID range
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

_CID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,128}$")


@lru_cache(maxsize=1)
def _bootstrap():
    from src.app.bootstrap import bootstrap
    return bootstrap()


def _error_response(msg: str, cid: str, mode: str) -> dict[str, Any]:
    logger.error("process_system_error", extra={"error": msg, "correlation_id": cid, "mode": mode})
    return {"status": "failed", "error_message": msg, "correlation_id": cid, "mode": mode}


def process_system(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Main callable — delegates to the correct use case.
    Returns a structured dict (never raises to the caller).
    """
    if input_data is None:
        input_data = {}

    mode = str(input_data.get("mode", "daily")).strip().lower()
    cid = str(input_data.get("correlation_id", "")).strip()

    if not cid or not _CID_RE.match(cid):
        cid = str(uuid.uuid4())

    try:
        container = _bootstrap()
    except SystemExit:
        return _error_response("Bootstrap failed — check configuration.", cid, mode)

    # --- daily ---
    if mode == "daily":
        result = container.run_daily_use_case.execute(correlation_id=cid)

    # --- reprocess_date_range ---
    elif mode == "reprocess_date_range":
        try:
            start = date.fromisoformat(str(input_data["start_date"]))
            end = date.fromisoformat(str(input_data["end_date"]))
        except (KeyError, TypeError, ValueError):
            return _error_response("start_date and end_date must be YYYY-MM-DD.", cid, mode)

        try:
            result = container.reprocess_date_range_use_case.execute(
                start_date=start, end_date=end, correlation_id=cid
            )
        except (PermissionError, ValueError) as exc:
            return _error_response(str(exc), cid, mode)

    # --- reprocess_id_range ---
    elif mode == "reprocess_id_range":
        try:
            start_id = int(input_data["start_id"])
            end_id = int(input_data["end_id"])
        except (KeyError, TypeError, ValueError):
            return _error_response("start_id and end_id must be integers.", cid, mode)
        if start_id < 0 or end_id < start_id:
            return _error_response("start_id must be >= 0 and <= end_id.", cid, mode)

        from src.app.application.use_cases import ReprocessIdRangeUseCase
        use_case = ReprocessIdRangeUseCase(
            orchestrator=container.orchestrator,
            settings=container.settings,
            start_id=start_id,
            end_id=end_id,
        )
        result = use_case.execute(correlation_id=cid)

    else:
        return _error_response(f"Unknown mode: {mode!r}", cid, mode)

    return {
        "status": result.status,
        "mode": mode,
        "correlation_id": cid,
        "total_batches": result.total_batches,
        "total_processed": result.total_processed,
        "total_updated": result.total_updated,
        "total_errors": result.total_errors,
        "error_message": result.error_message,
    }

from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

from middleware.error_middleware import AppError, ValidationError

# feedback-service control endpoint on the internal docker network.
_FEEDBACK_BASE_URL = os.environ.get("FEEDBACK_SERVICE_URL", "http://feedback-service:8084")
_INTERNAL_SECRET = os.environ.get("FEEDBACK_INTERNAL_SECRET", "")


def _call_feedback(path: str, payload: dict, timeout: int = 25) -> dict:
    """POST to feedback-service. Maps its HTTP status to the dashboard error model
    (409 locked / 404 missing / 400 invalid) so the frontend gets a clean message."""
    url = f"{_FEEDBACK_BASE_URL}{path}"
    data = json.dumps(payload or {}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if _INTERNAL_SECRET:
        headers["X-Internal-Secret"] = _INTERNAL_SECRET
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        try:
            parsed = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            parsed = {}
        detail = parsed.get("detail") or parsed.get("error") or f"Feedback service error {exc.code}"
        # Preserve the status code (409 locked / 404 / 400) for the frontend.
        raise AppError(detail, status_code=exc.code if exc.code in (400, 404, 409) else 400)
    except Exception as exc:  # URLError / timeout / connection refused
        raise ValidationError(f"Feedback service is unavailable: {exc}")


def submit_feedback(comment_id: str, new_topic: Optional[str], new_sentiment: Optional[str], user_id: int) -> dict:
    if not (new_topic or new_sentiment):
        raise ValidationError("Provide a new topic and/or sentiment.")
    return _call_feedback(
        "/internal/feedback",
        {"comment_id": comment_id, "new_topic": new_topic, "new_sentiment": new_sentiment, "user_id": user_id},
    )


def submit_feedback_bulk(comment_ids: list[str], new_topic: Optional[str], new_sentiment: Optional[str], user_id: int) -> dict:
    if not comment_ids:
        raise ValidationError("Select at least one comment.")
    if not (new_topic or new_sentiment):
        raise ValidationError("Provide a new topic and/or sentiment.")
    return _call_feedback(
        "/internal/feedback/bulk",
        {"comment_ids": comment_ids, "new_topic": new_topic, "new_sentiment": new_sentiment, "user_id": user_id},
    )

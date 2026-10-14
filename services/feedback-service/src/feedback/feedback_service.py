"""
Correction orchestration (R3, R5, R7-bulk).

Single + bulk correction. The single-correction TX captures the ORIGINAL pipeline
labels into label_feedback BEFORE overwriting comments (R5), under a FOR UPDATE row
lock (serializes savers). First-writer-wins is enforced twice: the human_verified
check under the lock AND the UNIQUE(comment_id) on label_feedback (R3).
"""
from __future__ import annotations

import logging
import os
import uuid

from psycopg2 import errors as pgerrors

from config import settings
from db.connection import get_conn
from db.queries import Q
from feedback import topics_registry
from validation.sentiment_validator import is_valid_sentiment, normalize_sentiment
from validation.topic_normalizer import display_label, normalize_key
from validation.topic_sanitizer import sanitize_topic

logger = logging.getLogger(__name__)


def _prepare(raw_topic, raw_sentiment) -> dict:
    """Sanitize + validate the requested change once. Returns a prepared plan."""
    topic_changed = raw_topic is not None and str(raw_topic).strip() != ""
    sentiment_changed = raw_sentiment is not None and str(raw_sentiment).strip() != ""
    plan = {
        "ok": True, "reason": None,
        "topic_changed": topic_changed, "sentiment_changed": sentiment_changed,
        "topic_display": None, "topic_key": None, "sentiment": None,
    }
    if not (topic_changed or sentiment_changed):
        return {**plan, "ok": False, "reason": "Provide a new topic and/or sentiment."}
    if topic_changed:
        ok, val = sanitize_topic(raw_topic, settings.topic_max_len)
        if not ok:
            return {**plan, "ok": False, "reason": val}
        plan["topic_display"] = display_label(val)
        plan["topic_key"] = normalize_key(val)
    if sentiment_changed:
        if not is_valid_sentiment(raw_sentiment):
            return {**plan, "ok": False, "reason": "Sentiment must be positive, neutral, or negative."}
        plan["sentiment"] = normalize_sentiment(raw_sentiment)
    return plan


def _apply(cur, comment_id: str, plan: dict, user_id, batch_id) -> dict:
    """Apply one correction inside an open cursor/TX. Caller owns commit/rollback."""
    cur.execute(Q.LOCK_COMMENT, {"cid": comment_id})
    row = cur.fetchone()
    if row is None:
        return {"status": "not_found"}
    pipeline_topic, pipeline_sentiment, human_verified = row
    if human_verified:
        return {"status": "locked"}

    if plan["topic_changed"]:
        topics_registry.upsert_topic(cur, plan["topic_key"], plan["topic_display"], user_id)
        eff_topic = topics_registry.canonical_display(cur, plan["topic_key"], plan["topic_display"])
        human_topic, human_key = eff_topic, plan["topic_key"]
    else:
        eff_topic = pipeline_topic
        human_topic, human_key = pipeline_topic, normalize_key(pipeline_topic or "")

    eff_sentiment = plan["sentiment"] if plan["sentiment_changed"] else pipeline_sentiment

    # Capture the ORIGINAL labels FIRST (R5); UNIQUE(comment_id) is the race backstop.
    cur.execute(
        Q.INSERT_FEEDBACK,
        {
            "comment_id": comment_id,
            "pipeline_topic": pipeline_topic,
            "pipeline_sentiment": pipeline_sentiment,
            "human_topic": human_topic,
            "human_sentiment": eff_sentiment,
            "human_topic_key": human_key,
            "topic_changed": plan["topic_changed"],
            "sentiment_changed": plan["sentiment_changed"],
            "user_id": user_id,
            "batch_id": batch_id,
        },
    )
    cur.execute(
        Q.UPDATE_COMMENT,
        {"topic": eff_topic, "sentiment": eff_sentiment, "user_id": user_id, "cid": comment_id},
    )
    return {"status": "ok", "effective_topic": eff_topic, "effective_sentiment": eff_sentiment}


def correct(comment_id: str, raw_topic, raw_sentiment, user_id) -> dict:
    plan = _prepare(raw_topic, raw_sentiment)
    if not plan["ok"]:
        return {"status": "invalid", "reason": plan["reason"]}
    try:
        with get_conn() as conn:
            result = _apply(conn.cursor(), comment_id, plan, user_id, None)
    except pgerrors.UniqueViolation:
        return {"status": "locked"}
    if result.get("status") == "ok":
        _bump_version()
        logger.info("feedback.applied", extra={"comment_id": comment_id})
    return result


def correct_bulk(comment_ids: list[str], raw_topic, raw_sentiment, user_id) -> dict:
    plan = _prepare(raw_topic, raw_sentiment)
    if not plan["ok"]:
        return {"status": "invalid", "reason": plan["reason"]}
    batch_id = str(uuid.uuid4())
    applied: list[str] = []
    skipped: list[dict] = []
    # Independent per-row TX → partial success (a locked/missing row never fails the batch).
    for cid in comment_ids:
        try:
            with get_conn() as conn:
                r = _apply(conn.cursor(), cid, plan, user_id, batch_id)
        except pgerrors.UniqueViolation:
            r = {"status": "locked"}
        if r.get("status") == "ok":
            applied.append(cid)
        else:
            skipped.append({"comment_id": cid, "reason": r.get("status", "error")})
    if applied:
        _bump_version()
    logger.info("feedback.bulk", extra={"batch_id": batch_id, "applied": len(applied), "skipped": len(skipped)})
    return {"status": "ok", "batch_id": batch_id, "applied": applied, "skipped": skipped}


def _bump_version() -> None:
    """Best-effort monotonic counter in Consul KV (feedback/version) for the Pass 2
    read cache. Never fails the correction if Consul is unreachable."""
    try:
        import consul
        c = consul.Consul(
            host=os.environ.get("CONSUL_HOST", "consul"),
            port=int(os.environ.get("CONSUL_PORT", "8500")),
        )
        _, data = c.kv.get("feedback/version")
        current = int(data["Value"]) if data and data.get("Value") else 0
        c.kv.put("feedback/version", str(current + 1))
    except Exception:  # noqa: BLE001 — coordination signal is best-effort
        pass

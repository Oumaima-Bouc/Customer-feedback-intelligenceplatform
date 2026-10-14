"""
Retraining export (R13): the curated (pipeline_label, human_label, text) dataset.
Read-only, indexed by created_at, off the dashboard hot path.
"""
from __future__ import annotations

import json

from db.connection import get_conn
from db.queries import Q


def export_rows(since: str | None = None, limit: int = 100_000) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(Q.EXPORT, {"since": since, "limit": limit})
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


def to_jsonl(rows: list[dict]) -> str:
    return "\n".join(json.dumps(r, default=str, ensure_ascii=False) for r in rows)

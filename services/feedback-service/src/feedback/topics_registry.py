"""
Persistent canonical topics registry (R10). Counts are never stored here — they are
derived live from `comments` (Pass 2), so the registry can't drift. A row's mere
existence is what lets a human-created topic persist even at zero comments.
"""
from __future__ import annotations

from db.queries import Q


def upsert_topic(cur, topic_key: str, display_label: str, user_id) -> None:
    """Register a human topic if its normalized key is new (idempotent)."""
    cur.execute(
        Q.UPSERT_TOPIC,
        {"topic_key": topic_key, "display_label": display_label, "created_by": user_id},
    )


def canonical_display(cur, topic_key: str, fallback: str) -> str:
    """Return the registry's display label for a key (existing or just-inserted)."""
    cur.execute(Q.GET_TOPIC_DISPLAY, {"topic_key": topic_key})
    row = cur.fetchone()
    return row[0] if row and row[0] else fallback

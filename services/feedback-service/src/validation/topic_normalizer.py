"""
Topic normalization (R9, MVP): canonical key = lower(collapse_ws(trim(topic))).

Merges only case/whitespace variants ("Billing Issue" ≡ "billing  issue"); plurals
and synonyms do NOT merge — that is the production similarity step (spec §10). The
caller preserves the user's original casing as the display label.
"""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def normalize_key(topic: str) -> str:
    return _WS.sub(" ", (topic or "").strip()).lower()


def display_label(topic: str) -> str:
    """Whitespace-collapsed, trimmed — original casing preserved for display."""
    return _WS.sub(" ", (topic or "").strip())

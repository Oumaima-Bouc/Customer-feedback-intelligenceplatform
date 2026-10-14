"""Sentiment validation — membership in the model's 3-label set (R2)."""
from __future__ import annotations

ALLOWED_SENTIMENTS = ("positive", "neutral", "negative")


def normalize_sentiment(raw: str) -> str:
    return (raw or "").strip().lower()


def is_valid_sentiment(raw: str) -> bool:
    return normalize_sentiment(raw) in ALLOWED_SENTIMENTS

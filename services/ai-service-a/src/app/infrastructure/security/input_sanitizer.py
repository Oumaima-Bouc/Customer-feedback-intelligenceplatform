"""
input_sanitizer.py

Validates and sanitizes text before it enters the NLP pipeline.
Critical defence layer against:
  - Prompt injection via crafted comment text
  - Control-character smuggling
  - Oversized inputs causing OOM
  - Null-byte / binary injection
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Prompt-injection detection patterns (conservative, low false-positive)
# ---------------------------------------------------------------------------
_PROMPT_INJECTION_PATTERNS: list[re.Pattern] = [
    # Classic instruction override attempts
    re.compile(r"(?i)(ignore\s+(all\s+)?(previous|above|prior)\s+instructions?)"),
    re.compile(r"(?i)(you\s+are\s+now\s+(?:a|an)\s+\w+)"),
    re.compile(r"(?i)(system\s*:\s*|user\s*:\s*|assistant\s*:\s*)"),
    re.compile(r"(?i)(act\s+as\s+(?:a|an)\s+\w+)"),
    re.compile(r"(?i)(forget\s+(all\s+)?your\s+(previous\s+)?instructions?)"),
    # Role/token injection
    re.compile(r"<\|(?:im_start|im_end|endoftext|system|user|assistant)\|>"),
    re.compile(r"\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>"),
    # Null bytes and C0/C1 control characters (except \t \n \r)
    re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"),
]

_MAX_TEXT_LENGTH: int = 10_000  # absolute ceiling before settings apply


@dataclass(frozen=True)
class SanitizationResult:
    is_safe: bool
    sanitized_text: str
    rejection_reason: str | None = None


def sanitize_input(text: str, max_length: int = 2000) -> SanitizationResult:
    """
    Returns SanitizationResult.is_safe=False and a reason if the input
    should be rejected entirely; otherwise returns cleaned text.

    This does NOT modify text for business purposes — that is the Normalizer's job.
    It only removes/rejects genuinely hostile content.
    """
    if not isinstance(text, str):
        return SanitizationResult(False, "", "non-string input")

    # Hard ceiling against extreme inputs
    if len(text) > _MAX_TEXT_LENGTH:
        text = text[:_MAX_TEXT_LENGTH]

    # Strip null bytes unconditionally
    text = text.replace("\x00", "")

    # Reject if prompt-injection patterns detected
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            return SanitizationResult(
                False,
                "",
                f"potential prompt injection detected (pattern: {pattern.pattern[:40]})",
            )

    # Apply configured max length (after injection check, not before)
    capped = text[:max_length]

    return SanitizationResult(is_safe=True, sanitized_text=capped)


def bulk_sanitize(
    texts: list[str], max_length: int = 2000
) -> tuple[list[SanitizationResult], list[int]]:
    """
    Returns (results, rejected_indices).
    Callers must log rejected_indices at WARNING level.
    """
    results = [sanitize_input(t, max_length) for t in texts]
    rejected = [i for i, r in enumerate(results) if not r.is_safe]
    return results, rejected

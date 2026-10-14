"""
Free-text topic sanitization (R12) — backend authority, mirrors ai-service-a's
input_sanitizer patterns (base spec §15.4). Data-quality + safety: keeps the topic
vocabulary clean. (All SQL is parameter-bound, so this is not the injection defense
of last resort, but it screens the same hostile-input family.)

sanitize_topic(raw) -> (ok: bool, value: str)
  ok True  → value is the cleaned (collapsed/trimmed) topic
  ok False → value is an operator-facing rejection reason
"""
from __future__ import annotations

import re

# Phrase / token level prompt-injection (the family input_sanitizer screens).
_INJECTION = [
    re.compile(r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+instructions?"),
    re.compile(r"(?i)\b(system|user|assistant)\s*:"),
    re.compile(r"\[/?INST\]|<<SYS>>|<</SYS>>|<\|"),
]
# Null byte + C0/C1 control characters.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# Collapse internal whitespace.
_WS = re.compile(r"\s+")
# Allowed charset: Unicode letters/digits/_ (\w with UNICODE), space, basic punctuation.
# This rejects code/HTML/SQL symbols (< > ; * ' " etc.) by construction.
_ALLOWED = re.compile(r"^[\w\s\-/&.()]+$", re.UNICODE)
# "Only digits" (with optional spaces) — rejected even though digits are otherwise allowed.
_ONLY_DIGITS = re.compile(r"^[\d\s]+$")


def sanitize_topic(raw: str, max_len: int = 80) -> tuple[bool, str]:
    if not isinstance(raw, str):
        return False, "Topic must be text."
    if _CONTROL.search(raw):
        return False, "Topic contains control characters that aren't allowed."
    for pat in _INJECTION:
        if pat.search(raw):
            return False, "Topic contains text patterns that aren't allowed."

    text = _WS.sub(" ", raw.replace("\x00", "")).strip()
    if not text:
        return False, "Topic cannot be empty."
    if len(text) > max_len:
        return False, f"Topic must be at most {max_len} characters."
    if _ONLY_DIGITS.match(text):
        return False, "Topic cannot be only numbers."
    if not _ALLOWED.match(text):
        return False, "Topic may contain letters, numbers, spaces and - _ / & . ( ) only."
    return True, text

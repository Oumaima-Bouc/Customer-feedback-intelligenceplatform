"""
secret_redaction.py
Structlog processor that strips secrets from log records before emission.
"""
from __future__ import annotations

import re
from typing import Any


_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "password", "passwd", "db_password", "db_pass",
        "admin_api_key", "api_key", "token", "secret",
        "dsn", "database_url", "connection_string",
        "authorization", "x-api-key", "bearer",
    }
)

_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"(password|passwd|api_key|token|secret)=[^\s&\"']+", re.IGNORECASE),
    re.compile(r"postgresql\+\w+://[^:]+:[^@]+@"),   # DSN password fragment
]


def _mask_value(v: Any) -> str:
    return "***REDACTED***"


def _redact_dict(d: dict) -> dict:
    """Recursively redact secret keys from a dict."""
    out: dict = {}
    for k, v in d.items():
        if isinstance(k, str) and k.lower().replace("-", "_") in _SECRET_KEYS:
            out[k] = _mask_value(v)
        elif isinstance(v, dict):
            out[k] = _redact_dict(v)
        elif isinstance(v, str):
            out[k] = _redact_str(v)
        else:
            out[k] = v
    return out


def _redact_str(s: str) -> str:
    for pattern in _SECRET_PATTERNS:
        s = pattern.sub(lambda m: _mask_value(m), s)
    return s


def redact_secrets_processor(logger: Any, method: str, event_dict: dict) -> dict:
    """
    Structlog processor — install near the end of the processor chain,
    BEFORE the renderer.
    """
    return _redact_dict(event_dict)

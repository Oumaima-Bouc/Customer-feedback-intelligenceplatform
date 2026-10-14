from __future__ import annotations
from typing import Any
from middleware.error_middleware import ValidationError
def require_fields(data: dict, *fields: str) -> None:
    missing = [f for f in fields if not data.get(f)]
    if missing: raise ValidationError(f"Missing required fields: {', '.join(missing)}")
def sanitize_str(value: Any, max_length: int = 255) -> str: return str(value).strip()[:max_length]

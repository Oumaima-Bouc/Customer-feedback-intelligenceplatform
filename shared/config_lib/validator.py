"""
validator.py — Config validation before application.

RULE: If validation fails, reject update, keep old config, log error, notify dashboard.
The service MUST NEVER enter an invalid runtime state.
"""
from __future__ import annotations

import logging
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from shared.config_lib.schema import (
    AIServiceAConfig,
    AIServiceBConfig,
    ConfigEnvelope,
    FeedbackServiceConfig,
    GlobalConfig,
    ReplyServiceConfig,
)

logger = logging.getLogger(__name__)

_SCHEMA_MAP: dict[str, Type[BaseModel]] = {
    "global": GlobalConfig,
    "ai-service-a": AIServiceAConfig,
    "ai-service-b": AIServiceBConfig,
    "reply-service": ReplyServiceConfig,
    "feedback-service": FeedbackServiceConfig,
}


def validate_config(service_name: str, raw: dict[str, Any]) -> BaseModel | None:
    """
    Validate a raw config dict against the schema for `service_name`.

    Returns:
        Parsed Pydantic model on success, None on validation failure.
    """
    schema_cls = _SCHEMA_MAP.get(service_name)
    if schema_cls is None:
        logger.error("validate_config.unknown_service", extra={"service": service_name})
        return None

    try:
        return schema_cls.model_validate(raw)
    except ValidationError as exc:
        logger.error(
            "validate_config.validation_failed",
            extra={
                "service": service_name,
                "errors": exc.errors(),
            },
        )
        return None


def validate_envelope(raw: dict[str, Any]) -> ConfigEnvelope | None:
    """Validate the outer envelope (version + settings)."""
    try:
        return ConfigEnvelope.model_validate(raw)
    except ValidationError as exc:
        logger.error("validate_envelope.failed", extra={"errors": exc.errors()})
        return None


def diff_config(old: BaseModel, new: BaseModel) -> set[str]:
    """
    Returns the set of dotted key paths that changed between two config objects.
    Only works on flat or single-nested Pydantic models.
    """
    changed: set[str] = set()
    old_dict = old.model_dump()
    new_dict = new.model_dump()

    def _diff(prefix: str, a: dict, b: dict) -> None:
        all_keys = set(a.keys()) | set(b.keys())
        for key in all_keys:
            full_key = f"{prefix}.{key}" if prefix else key
            va, vb = a.get(key), b.get(key)
            if isinstance(va, dict) and isinstance(vb, dict):
                _diff(full_key, va, vb)
            elif va != vb:
                changed.add(full_key)

    _diff("", old_dict, new_dict)
    return changed

"""
Logging configuration for AI Service A.

Delegates to shared/logging_lib/setup.py which provides:
  - Dual-sink output: stdout + rotating JSONL file (/logs/ai-service-a.jsonl)
  - Structlog JSON processor chain with service/level/timestamp/logger fields
  - Secret redaction (passwords, tokens, DSNs never appear in logs)
  - Noisy third-party loggers silenced at WARNING

This module exists as a thin adapter so bootstrap.py can call
configure_logging(settings) without knowing about the shared library.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.app.infrastructure.config.settings import Settings

logger = logging.getLogger(__name__)


def configure_logging(settings: "Settings") -> None:
    """
    Configure structured logging for AI Service A.
    Called once by bootstrap.py before any other log output.
    """
    from shared.logging_lib.setup import configure_service_logging

    configure_service_logging(
        service_name="ai-service-a",
        log_level=settings.app.log_level,
        log_format=settings.app.log_format,
        log_dir="/logs",
        enable_file_logging=True,
        enable_secret_redaction=settings.security.secret_redaction_enabled,
    )

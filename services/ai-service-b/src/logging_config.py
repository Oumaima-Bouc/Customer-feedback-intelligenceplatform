"""
Logging configuration for AI Service B (Meta Scraper).

Delegates to shared/logging_lib/setup.py which provides:
  - Dual-sink output: stdout + rotating JSONL file (/logs/ai-service-b.jsonl)
  - Structlog JSON processor chain with service/level/timestamp/logger fields
  - Secret redaction (Meta access tokens and DB credentials never appear in logs)
  - Noisy third-party loggers silenced at WARNING

Imported once at process startup by entrypoint.py (via 'import logging_config').
The side-effect of the import triggers configure_service_logging().
"""
from __future__ import annotations

import os

from shared.logging_lib.setup import configure_service_logging

configure_service_logging(
    service_name=os.environ.get("SERVICE_NAME", "ai-service-b"),
    log_level=os.environ.get("LOG_LEVEL", "INFO"),
    log_format="json",
    log_dir="/logs",
    enable_file_logging=True,
    enable_secret_redaction=True,
)

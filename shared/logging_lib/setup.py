"""
shared/logging_lib/setup.py — Enterprise structured logging for the AI Platform.

Every service calls configure_service_logging() once at process startup.

Output design (dual-sink):
  ┌─────────────────────────────────────────────────────────────────────┐
  │  structlog  (JSON processors chain)                                  │
  │      │                                                               │
  │      ▼  renders  →  one-line JSON string per event                  │
  │  Python stdlib root logger                                           │
  │      │                                                               │
  │      ├──► StreamHandler (stdout)  ─────► Docker captures           │
  │      │                                   → Promtail via file         │
  │      └──► RotatingFileHandler    ──────► /logs/{service}.jsonl      │
  │           50 MB × 10 rotations           (shared volume)            │
  │           = up to 500 MB per service     → Promtail reads directly  │
  └─────────────────────────────────────────────────────────────────────┘

Promtail parses each JSONL line, extracts `service` and `level` as Loki
labels, and uses the embedded `timestamp` field as the log time.

Log retention:
  - File: 500 MB rolling window per service (10 × 50 MB)
  - Loki: 31-day policy configured in loki-config.yml

Noisy third-party loggers are silenced at WARNING level.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any, Callable

import structlog


# ---------------------------------------------------------------------------
# Secret redaction patterns (same as AI Service A's secret_redaction.py)
# ---------------------------------------------------------------------------
import re

_SECRET_KEYS: frozenset[str] = frozenset({
    "password", "passwd", "db_password", "db_pass",
    "admin_api_key", "api_key", "token", "secret",
    "dsn", "database_url", "connection_string",
    "authorization", "x-api-key", "bearer",
    "access_token", "meta_access_token",
})

_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"(password|passwd|api_key|token|secret)=[^\s&\"']+", re.IGNORECASE),
    re.compile(r"postgresql\+\w+://[^:]+:[^@]+@"),
]


def _redact_value(_: Any) -> str:
    return "***REDACTED***"


def _redact_str(s: str) -> str:
    for pattern in _SECRET_PATTERNS:
        s = pattern.sub(lambda m: _redact_value(m), s)
    return s


def _redact_dict(d: dict) -> dict:
    out: dict = {}
    for k, v in d.items():
        if isinstance(k, str) and k.lower().replace("-", "_") in _SECRET_KEYS:
            out[k] = _redact_value(v)
        elif isinstance(v, dict):
            out[k] = _redact_dict(v)
        elif isinstance(v, str):
            out[k] = _redact_str(v)
        else:
            out[k] = v
    return out


def _redact_secrets_processor(
    logger: Any, method: str, event_dict: dict
) -> dict:
    """Structlog processor: strips secrets before rendering."""
    return _redact_dict(event_dict)


# ---------------------------------------------------------------------------
# Service-name injection processor
# ---------------------------------------------------------------------------
def _make_service_processor(service_name: str) -> Callable:
    """Returns a structlog processor that stamps every log with 'service'."""
    def _add_service(logger: Any, method: str, event_dict: dict) -> dict:
        event_dict["service"] = service_name
        return event_dict
    return _add_service


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def configure_service_logging(
    service_name: str,
    log_level: str = "INFO",
    log_format: str = "json",
    log_dir: str = "/logs",
    enable_file_logging: bool = True,
    enable_secret_redaction: bool = True,
) -> None:
    """
    One-call logging bootstrap for every AI Platform service.

    Parameters
    ----------
    service_name:
        Identifies the service in every log line and in the log filename.
        Example: "ai-service-a", "dashboard-service".
    log_level:
        Python log level string: DEBUG | INFO | WARNING | ERROR | CRITICAL.
    log_format:
        "json"  → JSONRenderer (production default, Promtail-friendly)
        "text"  → ConsoleRenderer (human-readable, useful for local dev)
    log_dir:
        Directory for the rotating log file.  Created if absent.
        Gracefully falls back to stdout-only if the path is not writable.
    enable_file_logging:
        Set False to skip file output entirely (e.g., unit tests).
    enable_secret_redaction:
        Run the secret redaction processor before rendering.

    Side-effects
    ------------
    - Reconfigures structlog globally.
    - Reconfigures the Python stdlib root logger.
    - Adds up to two handlers (stdout + file) to the root logger.
    - Silences urllib3, httpcore, httpx, transformers, torch at WARNING.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # ── Structlog processor chain ──────────────────────────────────────────
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        _make_service_processor(service_name),          # stamps `service`
        structlog.stdlib.add_logger_name,               # stamps `logger`
        structlog.stdlib.add_log_level,                 # stamps `level`
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),    # stamps `timestamp`
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if enable_secret_redaction:
        shared_processors.append(_redact_secrets_processor)

    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ── Stdlib root logger ─────────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()                   # remove any existing handlers

    # Sink 1 — stdout (Docker log capture)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    # Sink 2 — rotating JSONL file (Promtail reads from shared volume)
    if enable_file_logging:
        _add_file_handler(root, service_name, log_dir, level, formatter)

    # ── Silence noisy third-party loggers ──────────────────────────────────
    _NOISY = (
        "urllib3", "httpcore", "httpx",
        "transformers", "torch", "sentence_transformers",
        "umap", "numba", "asyncio", "apscheduler",
        "uvicorn.access",    # HTTP access log is too verbose at INFO
    )
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)

    # First log line confirms the configuration
    log = structlog.get_logger(__name__)
    log.info(
        "logging.configured",
        service=service_name,
        level=log_level,
        format=log_format,
        file_logging=enable_file_logging,
        log_dir=log_dir,
        secret_redaction=enable_secret_redaction,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _add_file_handler(
    root: logging.Logger,
    service_name: str,
    log_dir: str,
    level: int,
    formatter: logging.Formatter,
) -> None:
    """
    Attach a RotatingFileHandler to the root logger.

    File: {log_dir}/{service_name}.jsonl
    Rotation: 50 MB per file, 10 backup files kept → up to 500 MB per service.

    Fails silently (logs a warning to stdout) if the directory cannot be
    created or the file cannot be opened — the service keeps running with
    stdout-only logging.
    """
    try:
        log_path = Path(log_dir) / f"{service_name}.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_path),
            maxBytes=50 * 1024 * 1024,  # 50 MB per file
            backupCount=10,              # 10 rotated files → max 500 MB
            encoding="utf-8",
            delay=False,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    except (PermissionError, OSError, IOError) as exc:
        # Non-fatal: emit a warning on stdout and continue without file logging.
        logging.warning(
            f"[logging_lib] Cannot open log file for {service_name!r}: {exc}. "
            "Falling back to stdout-only logging."
        )

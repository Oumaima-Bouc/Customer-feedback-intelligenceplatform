"""
Shared Job Execution Tracker — used by both ai-service-a and ai-service-b.

Supports two DB drivers:
  - asyncpg (ai-service-b, async)
  - psycopg2 (ai-service-a via SQLAlchemy, sync)

Usage:
    tracker = JobTracker(dsn=..., service="ai-service-a")
    async with tracker.start("ml_pipeline") as job:
        job.log("INFO", "pipeline.start", "Starting pipeline")
        ...
        job.set_counts(records_in=510, records_out=510)

    # Or sync:
    tracker = JobTracker(dsn=..., service="ai-service-a", sync=True)
    with tracker.start_sync("ml_pipeline") as job:
        job.log_sync("INFO", "pipeline.start", "Starting")
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class JobExecution:
    """Represents a single job execution. Accumulates log entries and metadata."""
    execution_id: Optional[int] = None
    job_name: str = ""
    service: str = ""
    status: str = "running"
    started_at: Optional[datetime] = None
    records_in: int = 0
    records_out: int = 0
    error_count: int = 0
    error_message: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    _log_buffer: list = field(default_factory=list)
    _start_time: float = 0.0

    def set_counts(self, records_in: int = 0, records_out: int = 0) -> None:
        self.records_in = records_in
        self.records_out = records_out

    def add_metadata(self, **kwargs) -> None:
        self.metadata.update(kwargs)

    def log(self, level: str, event: str, message: str = "", **details) -> None:
        """Buffer a log entry (flushed on completion)."""
        self._log_buffer.append({
            "level": level.upper(),
            "event": event,
            "message": message,
            "details": details,
            "logged_at": datetime.now(timezone.utc),
        })

    def log_sync(self, level: str, event: str, message: str = "", **details) -> None:
        """Alias for sync usage."""
        self.log(level, event, message, **details)


class JobTracker:
    """
    Manages job execution lifecycle — insert on start, update on finish,
    bulk-insert log entries.
    """

    def __init__(self, dsn: str, service: str, sync: bool = False) -> None:
        self._dsn = dsn
        self._service = service
        self._sync = sync

    # ------------------------------------------------------------------
    # ASYNC interface (for ai-service-b / asyncpg)
    # ------------------------------------------------------------------
    @asynccontextmanager
    async def start(self, job_name: str, **meta):
        """Async context manager for tracking a job execution."""
        job = JobExecution(
            job_name=job_name,
            service=self._service,
            started_at=datetime.now(timezone.utc),
            _start_time=time.monotonic(),
            metadata=meta,
        )

        try:
            import asyncpg
            conn = await asyncpg.connect(self._dsn)
            try:
                job.execution_id = await conn.fetchval(
                    """
                    INSERT INTO job_executions (job_name, service, status, started_at, metadata)
                    VALUES ($1, $2, 'running', $3, $4::jsonb)
                    RETURNING id
                    """,
                    job_name, self._service, job.started_at,
                    json.dumps(job.metadata),
                )
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("job_tracker.start_failed", extra={"error": str(exc)})

        try:
            yield job
            job.status = "completed"
        except Exception as exc:
            job.status = "failed"
            job.error_count += 1
            job.error_message = str(exc)[:2000]
            job.log("ERROR", "job.unhandled_error", str(exc))
            raise
        finally:
            await self._finalize_async(job)

    async def _finalize_async(self, job: JobExecution) -> None:
        """Update execution row + flush log entries (async)."""
        if not job.execution_id:
            return

        duration_ms = int((time.monotonic() - job._start_time) * 1000)

        try:
            import asyncpg
            conn = await asyncpg.connect(self._dsn)
            try:
                await conn.execute(
                    """
                    UPDATE job_executions
                    SET status = $1, finished_at = NOW(), duration_ms = $2,
                        records_in = $3, records_out = $4,
                        error_count = $5, error_message = $6,
                        metadata = $7::jsonb
                    WHERE id = $8
                    """,
                    job.status, duration_ms, job.records_in, job.records_out,
                    job.error_count, job.error_message,
                    json.dumps(job.metadata), job.execution_id,
                )

                if job._log_buffer:
                    await conn.executemany(
                        """
                        INSERT INTO job_log_entries
                            (execution_id, logged_at, level, event, message, details)
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                        """,
                        [
                            (
                                job.execution_id,
                                entry["logged_at"],
                                entry["level"],
                                entry["event"],
                                entry["message"],
                                json.dumps(entry["details"]),
                            )
                            for entry in job._log_buffer
                        ],
                    )
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("job_tracker.finalize_failed", extra={"error": str(exc)})

    # ------------------------------------------------------------------
    # SYNC interface (for ai-service-a / psycopg2 or SQLAlchemy)
    # ------------------------------------------------------------------
    @contextmanager
    def start_sync(self, job_name: str, **meta):
        """Sync context manager for tracking a job execution."""
        job = JobExecution(
            job_name=job_name,
            service=self._service,
            started_at=datetime.now(timezone.utc),
            _start_time=time.monotonic(),
            metadata=meta,
        )

        try:
            import psycopg2
            conn = psycopg2.connect(self._dsn)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO job_executions (job_name, service, status, started_at, metadata)
                VALUES (%s, %s, 'running', %s, %s::jsonb)
                RETURNING id
                """,
                (job_name, self._service, job.started_at, json.dumps(job.metadata)),
            )
            job.execution_id = cur.fetchone()[0]
            cur.close()
            conn.close()
        except Exception as exc:
            logger.warning("job_tracker.start_sync_failed", extra={"error": str(exc)})

        try:
            yield job
            job.status = "completed"
        except Exception as exc:
            job.status = "failed"
            job.error_count += 1
            job.error_message = str(exc)[:2000]
            job.log("ERROR", "job.unhandled_error", str(exc))
            raise
        finally:
            self._finalize_sync(job)

    def _finalize_sync(self, job: JobExecution) -> None:
        """Update execution row + flush log entries (sync)."""
        if not job.execution_id:
            return

        duration_ms = int((time.monotonic() - job._start_time) * 1000)

        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(self._dsn)
            conn.autocommit = True
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE job_executions
                SET status = %s, finished_at = NOW(), duration_ms = %s,
                    records_in = %s, records_out = %s,
                    error_count = %s, error_message = %s,
                    metadata = %s::jsonb
                WHERE id = %s
                """,
                (
                    job.status, duration_ms, job.records_in, job.records_out,
                    job.error_count, job.error_message,
                    json.dumps(job.metadata), job.execution_id,
                ),
            )

            if job._log_buffer:
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    INSERT INTO job_log_entries
                        (execution_id, logged_at, level, event, message, details)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    [
                        (
                            job.execution_id,
                            entry["logged_at"],
                            entry["level"],
                            entry["event"],
                            entry["message"],
                            json.dumps(entry["details"]),
                        )
                        for entry in job._log_buffer
                    ],
                )

            cur.close()
            conn.close()
        except Exception as exc:
            logger.warning("job_tracker.finalize_sync_failed", extra={"error": str(exc)})

"""
PostgreSQL infrastructure layer.

Includes:
- session.py (engine creation)
- unit_of_work.py (transaction context manager)
- postgres_comment_repository.py
- postgres_checkpoint_repository.py
- postgres_topic_tracking_repository.py

Security: ALL queries use SQLAlchemy text() with bound parameters.
         No string formatting of user-supplied values into SQL.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.app.domain.ports import (
    CheckpointRepositoryPort,
    CheckpointValue,
    CommentRecord,
    CommentRepositoryPort,
    EnrichmentUpdate,
    TopicDailyRecord,
    TopicTrackingRepositoryPort,
)
from src.app.infrastructure.config.settings import DatabaseSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------
def create_db_engine(settings: DatabaseSettings) -> Engine:
    """
    Creates a SQLAlchemy 2 engine with hardened options.
    The DSN secret is never logged — only the redacted form is.
    """
    engine = create_engine(
        settings.secret_dsn,   # Contains password — NEVER pass to logger
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
        pool_pre_ping=True,    # Detects stale connections
        connect_args={
            "connect_timeout": settings.connect_timeout_seconds,
            "options": (
                f"-c statement_timeout={settings.statement_timeout_ms}"
                f" -c lock_timeout={settings.lock_timeout_ms}"
                f" -c application_name={settings.application_name}"
            ),
        },
    )
    logger.info("db_engine_created", extra={"dsn": settings.dsn})
    return engine


# ---------------------------------------------------------------------------
# Unit of Work
# ---------------------------------------------------------------------------
class UnitOfWork:
    """
    Context manager that owns a single SQLAlchemy session.
    Both comment updates and checkpoint saves execute inside ONE transaction,
    ensuring the atomicity required by the architecture spec.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self.session: Optional[Session] = None

    def __enter__(self) -> "UnitOfWork":
        self.session = self._session_factory()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self.rollback()
        # No auto-commit: callers must call uow.commit() explicitly
        if self.session:
            self.session.close()
            self.session = None

    def commit(self) -> None:
        assert self.session is not None
        self.session.commit()

    def rollback(self) -> None:
        assert self.session is not None
        self.session.rollback()


# ---------------------------------------------------------------------------
# Comment Repository
# ---------------------------------------------------------------------------
class PostgresCommentRepository(CommentRepositoryPort):

    def __init__(self, session: Session) -> None:
        self._session = session

    def fetch_batch(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        last_comment_id: str,
        batch_size: int,
        process_only_unclassified: bool,
        ignore_date_window: bool = False,
    ) -> list[CommentRecord]:
        """
        Keyset pagination query — no OFFSET/LIMIT drift.
        All parameters are bound — no interpolation into SQL string.
        When ignore_date_window=True, skips date filtering to process all rows.
        """
        # Clamp batch_size defensively
        safe_batch = max(1, min(batch_size, 4096))

        sql = text(
            """
            SELECT comment_id, text_content, created_at, source
            FROM comments
            WHERE (:ignore_date_window = TRUE OR (created_at >= :window_start AND created_at < :window_end))
              AND comment_id > :last_comment_id
              AND NOT human_verified            -- never re-label a human-corrected comment (Label Feedback R3/§8)
              AND (
                    :process_only_unclassified = FALSE
                 OR topic IS NULL
                 OR sentiment IS NULL
              )
            ORDER BY comment_id ASC
            LIMIT :batch_size
            """
        )
        rows = self._session.execute(
            sql,
            {
                "ignore_date_window": ignore_date_window,
                "window_start": window_start,
                "window_end": window_end,
                "last_comment_id": str(last_comment_id),
                "process_only_unclassified": process_only_unclassified,
                "batch_size": safe_batch,
            },
        ).fetchall()

        return [
            CommentRecord(
                comment_id=str(row.comment_id),
                text_content=str(row.text_content) if row.text_content else "",
                created_at=row.created_at,
                source=str(row.source) if row.source else None,
            )
            for row in rows
        ]

    def update_enrichment_batch(self, updates: list[EnrichmentUpdate]) -> int:
        """
        Bulk update using VALUES clause.
        Parameters are bound — NOT formatted into the SQL string.
        Writes: topic, sentiment, cluster_id, topic_label, fallback_used.
        """
        if not updates:
            return 0

        # Build VALUES list with numbered parameter placeholders
        value_clauses = []
        params: dict = {}
        for i, upd in enumerate(updates):
            value_clauses.append(
                f"(:cid_{i}, :topic_{i}, :sentiment_{i}, "
                f"CAST(:cluster_id_{i} AS int), :topic_label_{i}, CAST(:fallback_{i} AS boolean))"
            )
            params[f"cid_{i}"] = str(upd.comment_id)
            params[f"topic_{i}"] = str(upd.topic)[:256]
            params[f"sentiment_{i}"] = str(upd.sentiment)[:16]
            params[f"cluster_id_{i}"] = upd.cluster_id
            params[f"topic_label_{i}"] = str(upd.topic_label)[:256] if upd.topic_label else None
            params[f"fallback_{i}"] = upd.fallback_used

        values_sql = ", ".join(value_clauses)
        sql = text(
            f"""
            UPDATE comments AS c
            SET topic        = v.topic,
                sentiment    = v.sentiment,
                cluster_id   = v.cluster_id,
                topic_label  = v.topic_label,
                fallback_used = v.fallback_used,
                updated_at   = NOW()
            FROM (VALUES {values_sql})
                AS v(comment_id, topic, sentiment, cluster_id, topic_label, fallback_used)
            WHERE c.comment_id = v.comment_id
            """
        )
        result = self._session.execute(sql, params)
        return result.rowcount


# ---------------------------------------------------------------------------
# Checkpoint Repository
# ---------------------------------------------------------------------------
class PostgresCheckpointRepository(CheckpointRepositoryPort):

    def __init__(self, session: Session) -> None:
        self._session = session

    def load(self, key: str) -> Optional[CheckpointValue]:
        sql = text(
            """
            SELECT checkpoint_key, last_comment_id, last_run_at,
                   last_window_start, last_window_end
            FROM pipeline_checkpoints
            WHERE checkpoint_key = :key
            """
        )
        row = self._session.execute(sql, {"key": key}).fetchone()
        if row is None:
            return None
        return CheckpointValue(
            key=str(row.checkpoint_key),
            last_comment_id=str(row.last_comment_id),
            last_run_at=row.last_run_at,
            last_window_start=row.last_window_start,
            last_window_end=row.last_window_end,
        )

    def save(self, checkpoint: CheckpointValue) -> None:
        sql = text(
            """
            INSERT INTO pipeline_checkpoints
                (checkpoint_key, last_comment_id, last_run_at, last_window_start, last_window_end)
            VALUES (:key, :last_comment_id, NOW(), :window_start, :window_end)
            ON CONFLICT (checkpoint_key) DO UPDATE
                SET last_comment_id  = EXCLUDED.last_comment_id,
                    last_run_at      = EXCLUDED.last_run_at,
                    last_window_start = EXCLUDED.last_window_start,
                    last_window_end  = EXCLUDED.last_window_end
            """
        )
        self._session.execute(
            sql,
            {
                "key": checkpoint.key,
                "last_comment_id": str(checkpoint.last_comment_id),
                "window_start": checkpoint.last_window_start,
                "window_end": checkpoint.last_window_end,
            },
        )


# ---------------------------------------------------------------------------
# Topic Daily Tracking Repository
# ---------------------------------------------------------------------------
class PostgresTopicTrackingRepository(TopicTrackingRepositoryPort):
    """
    Persists per-topic daily aggregates for frontend charting.
    Uses UPSERT (INSERT ... ON CONFLICT DO UPDATE) so re-runs on the same
    date accumulate rather than duplicate.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_daily_tracking(self, records: list[TopicDailyRecord]) -> None:
        if not records:
            return

        sql = text(
            """
            INSERT INTO topic_daily_tracking
                (run_date, topic, comment_count, positive_pct, neutral_pct, negative_pct)
            VALUES
                (:run_date, :topic, :comment_count, :positive_pct, :neutral_pct, :negative_pct)
            ON CONFLICT (run_date, topic) DO UPDATE
                SET comment_count = topic_daily_tracking.comment_count + EXCLUDED.comment_count,
                    positive_pct  = EXCLUDED.positive_pct,
                    neutral_pct   = EXCLUDED.neutral_pct,
                    negative_pct  = EXCLUDED.negative_pct
            """
        )

        for record in records:
            self._session.execute(
                sql,
                {
                    "run_date": record.run_date,
                    "topic": record.topic,
                    "comment_count": record.comment_count,
                    "positive_pct": round(record.positive_pct, 2),
                    "neutral_pct": round(record.neutral_pct, 2),
                    "negative_pct": round(record.negative_pct, 2),
                },
            )

        logger.debug(
            "topic_daily_tracking_upserted",
            extra={"records_count": len(records)},
        )

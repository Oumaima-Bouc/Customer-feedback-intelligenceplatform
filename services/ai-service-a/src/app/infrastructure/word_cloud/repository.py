"""
PostgreSQL repository for word_cloud_snapshot table.

Atomic TRUNCATE + INSERT ensures readers never see partial data.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.domain.ports import WordCloudEntry, WordCloudRepositoryPort

logger = logging.getLogger(__name__)


class PostgresWordCloudRepository(WordCloudRepositoryPort):
    """Reads and writes the word_cloud_snapshot table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_snapshot(self, entries: list[WordCloudEntry]) -> None:
        """
        Atomically replaces the entire snapshot.
        TRUNCATE + batch INSERT within the caller's transaction.
        """
        self._session.execute(text("TRUNCATE TABLE word_cloud_snapshot"))

        if not entries:
            logger.info("word_cloud.snapshot_cleared")
            return

        now = datetime.now(timezone.utc)

        insert_sql = text("""
            INSERT INTO word_cloud_snapshot
                (word, frequency, positive_pct, neutral_pct, negative_pct, source, category, updated_at)
            VALUES
                (:word, :frequency, :positive_pct, :neutral_pct, :negative_pct, :source, :category, :updated_at)
        """)

        params = [
            {
                "word": e.word[:100],
                "frequency": e.frequency,
                "positive_pct": e.positive_pct,
                "neutral_pct": e.neutral_pct,
                "negative_pct": e.negative_pct,
                "source": e.source,
                "category": e.category,
                "updated_at": now,
            }
            for e in entries
        ]

        self._session.execute(insert_sql, params)

        logger.info(
            "word_cloud.snapshot_replaced",
            extra={"words_count": len(entries)},
        )

    def fetch_snapshot(self) -> list[WordCloudEntry]:
        """Returns all entries ordered by frequency DESC."""
        result = self._session.execute(
            text("""
                SELECT word, frequency, positive_pct, neutral_pct, negative_pct,
                       source, category
                FROM word_cloud_snapshot
                ORDER BY frequency DESC
            """)
        )

        return [
            WordCloudEntry(
                word=row.word,
                frequency=row.frequency,
                positive_pct=float(row.positive_pct),
                neutral_pct=float(row.neutral_pct),
                negative_pct=float(row.negative_pct),
                source=row.source,
                category=row.category,
            )
            for row in result
        ]

"""
Word Cloud Use Case — orchestrates the full word extraction pipeline.

Composition root wires strategies (dictionary + TF-IDF) and repository.
Called as the final step of the ML pipeline after topic+sentiment persist.
"""
from __future__ import annotations

import logging

from typing import Callable, Optional

from src.app.domain.ports import WordCloudEntry, WordExtractionStrategyPort
from src.app.infrastructure.config.settings import WordCloudSettings
from src.app.infrastructure.db.repositories import UnitOfWork
from src.app.infrastructure.word_cloud.repository import PostgresWordCloudRepository
from src.app.infrastructure.word_cloud.sentiment_scorer import score_words_by_sentiment

logger = logging.getLogger(__name__)


class RefreshWordCloudUseCase:
    """
    Fetches today's processed comments, runs extraction strategies,
    computes sentiment scores, and replaces the snapshot atomically.
    """

    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        strategies: list[WordExtractionStrategyPort],
        settings: WordCloudSettings,
        variant_to_canonical: Optional[dict[str, str]] = None,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._strategies = strategies
        self._settings = settings
        self._variant_to_canonical = variant_to_canonical or {}

    def execute(self) -> int:
        """
        Run the word cloud refresh.

        Returns:
            Number of words in the new snapshot.
        """
        if not self._settings.enabled:
            logger.info("word_cloud.disabled")
            return 0

        # 1. Fetch today's comments with sentiment from DB
        texts, sentiments = self._fetch_comments()

        if not texts:
            logger.info("word_cloud.no_comments_found")
            # Clear the snapshot so dashboard doesn't show stale data
            self._write_snapshot([])
            return 0

        logger.info(
            "word_cloud.extraction_start",
            extra={"comment_count": len(texts)},
        )

        # 2. Run all extraction strategies and merge results
        merged: dict[str, dict] = {}
        for strategy in self._strategies:
            if hasattr(strategy, "_min_freq"):
                strategy._min_freq = self._settings.min_frequency
            extracted = strategy.extract(texts)
            for word, info in extracted.items():
                if word not in merged:
                    merged[word] = info
                # Curated always wins over discovered for same word

        # 3. Filter by minimum frequency
        merged = {
            w: info for w, info in merged.items()
            if info["frequency"] >= self._settings.min_frequency
        }

        # 4. Cap at max_words (keep highest frequency)
        if len(merged) > self._settings.max_words:
            sorted_words = sorted(
                merged.items(),
                key=lambda x: x[1]["frequency"],
                reverse=True,
            )
            merged = dict(sorted_words[: self._settings.max_words])

        # 5. Compute per-word sentiment percentages
        entries = score_words_by_sentiment(
            merged, texts, sentiments,
            variant_to_canonical=self._variant_to_canonical,
        )

        # 6. Atomic replace
        self._write_snapshot(entries)

        logger.info(
            "word_cloud.refresh_complete",
            extra={
                "total_words": len(entries),
                "curated": sum(1 for e in entries if e.source == "curated"),
                "discovered": sum(1 for e in entries if e.source == "discovered"),
            },
        )
        return len(entries)

    def _fetch_comments(self) -> tuple[list[str], list[str]]:
        """Fetch comments from the last N hours that have sentiment assigned."""
        from sqlalchemy import text as sql_text

        texts: list[str] = []
        sentiments: list[str] = []

        try:
            with self._uow_factory() as uow:
                result = uow.session.execute(
                    sql_text("""
                        SELECT text_content, sentiment
                        FROM comments
                        WHERE created_at >= NOW() - MAKE_INTERVAL(hours => :hours)
                          AND sentiment IS NOT NULL
                          AND text_content IS NOT NULL
                          AND LENGTH(text_content) > 5
                        ORDER BY created_at DESC
                    """),
                    {"hours": self._settings.lookback_hours},
                )

                for row in result:
                    texts.append(row.text_content)
                    sentiments.append(row.sentiment)

        except Exception as exc:
            logger.error("word_cloud.fetch_comments_failed", extra={"error": str(exc)})

        return texts, sentiments

    def _write_snapshot(self, entries: list[WordCloudEntry]) -> None:
        """Write entries to DB in a single transaction."""
        try:
            with self._uow_factory() as uow:
                repo = PostgresWordCloudRepository(uow.session)
                repo.replace_snapshot(entries)
                uow.commit()
        except Exception as exc:
            logger.error(
                "word_cloud.write_snapshot_failed",
                extra={"error": str(exc)},
            )

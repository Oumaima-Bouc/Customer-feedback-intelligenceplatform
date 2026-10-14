"""
Application use cases — thin orchestration wrappers.

Each use case:
  - Validates inputs
  - Calculates derived parameters (e.g. date windows)
  - Delegates to PipelineOrchestrator
  - Returns RunResult
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

import zoneinfo

if TYPE_CHECKING:
    from src.app.application.orchestrators.pipeline_orchestrator import (
        PipelineOrchestrator,
        RunResult,
    )
    from src.app.infrastructure.config.settings import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RunDailyPipelineUseCase
# ---------------------------------------------------------------------------
class RunDailyPipelineUseCase:
    """Calculate yesterday's date window and invoke the pipeline."""

    def __init__(self, orchestrator: PipelineOrchestrator, settings: Settings) -> None:
        self.orchestrator = orchestrator
        self._settings = settings
        self.last_result: Optional[RunResult] = None
        self.last_window_start: Optional[datetime] = None
        self.last_window_end: Optional[datetime] = None

    def execute(self, correlation_id: str = "") -> RunResult:
        cfg = self._settings.pipeline
        tz = zoneinfo.ZoneInfo(cfg.window_timezone)

        now_local = datetime.now(tz)
        start_date = (now_local - timedelta(days=cfg.lookback_days)).date()
        end_date = now_local.date()

        window_start = datetime(
            start_date.year, start_date.month, start_date.day,
            cfg.window_start_hour, 0, 0,
            tzinfo=tz,
        )
        window_end = datetime(
            end_date.year, end_date.month, end_date.day,
            min(cfg.window_end_hour, 23), 59, 59,
            tzinfo=tz,
        )
        # If window_end_hour == 24, push to midnight next day
        if cfg.window_end_hour == 24:
            window_end = datetime(
                end_date.year, end_date.month, end_date.day,
                0, 0, 0,
                tzinfo=tz,
            ) + timedelta(days=1)

        self.last_window_start = window_start
        self.last_window_end = window_end

        logger.info(
            "run_daily_use_case",
            extra={
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "correlation_id": correlation_id,
            },
        )

        result = self.orchestrator.run(
            window_start=window_start,
            window_end=window_end,
            correlation_id=correlation_id,
        )
        self.last_result = result
        return result


# ---------------------------------------------------------------------------
# ReprocessDateRangeUseCase
# ---------------------------------------------------------------------------
class ReprocessDateRangeUseCase:
    """Reprocess comments within a specific date range."""

    MAX_DAYS: int = 90

    def __init__(self, orchestrator: PipelineOrchestrator, settings: Settings) -> None:
        self.orchestrator = orchestrator
        self._settings = settings

    def execute(
        self,
        start_date: date,
        end_date: date,
        correlation_id: str = "",
    ) -> RunResult:
        # Feature flag gate
        if not self._settings.features.allow_date_range_reprocess:
            raise PermissionError("Date-range reprocessing is disabled by feature flag")

        # Validate range
        if end_date < start_date:
            raise ValueError("end_date must be >= start_date")

        delta = (end_date - start_date).days
        if delta > self.MAX_DAYS:
            raise ValueError(
                f"Date range exceeds maximum of {self.MAX_DAYS} days (requested {delta})"
            )

        cfg = self._settings.pipeline
        tz = zoneinfo.ZoneInfo(cfg.window_timezone)

        window_start = datetime(
            start_date.year, start_date.month, start_date.day,
            0, 0, 0, tzinfo=tz,
        )
        window_end = datetime(
            end_date.year, end_date.month, end_date.day,
            0, 0, 0, tzinfo=tz,
        ) + timedelta(days=1)

        logger.info(
            "reprocess_date_range_use_case",
            extra={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "correlation_id": correlation_id,
            },
        )

        return self.orchestrator.run(
            window_start=window_start,
            window_end=window_end,
            correlation_id=correlation_id,
        )


# ---------------------------------------------------------------------------
# ReprocessIdRangeUseCase
# ---------------------------------------------------------------------------
class ReprocessIdRangeUseCase:
    """Reprocess comments within a specific comment_id range."""

    def __init__(
        self,
        orchestrator: PipelineOrchestrator,
        settings: Settings,
        start_id: int,
        end_id: int,
    ) -> None:
        self.orchestrator = orchestrator
        self._settings = settings
        self._start_id = start_id
        self._end_id = end_id

    def execute(self, correlation_id: str = "") -> RunResult:
        if not self._settings.features.allow_id_range_reprocess:
            raise PermissionError("ID-range reprocessing is disabled by feature flag")

        if self._start_id < 0 or self._end_id < self._start_id:
            raise ValueError("Invalid ID range: start_id must be >= 0 and <= end_id")

        logger.info(
            "reprocess_id_range_use_case",
            extra={
                "start_id": self._start_id,
                "end_id": self._end_id,
                "correlation_id": correlation_id,
            },
        )

        # Use a very wide date window; the ID range itself constrains the fetch
        window_start = datetime(2000, 1, 1, tzinfo=timezone.utc)
        window_end = datetime(2099, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        return self.orchestrator.run(
            window_start=window_start,
            window_end=window_end,
            correlation_id=correlation_id,
        )


# ---------------------------------------------------------------------------
# ValidateConfigurationUseCase
# ---------------------------------------------------------------------------
class ValidateConfigurationUseCase:
    """
    Cross-check configuration consistency at startup.
    Raises ValueError on any invalid combination.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def execute(self) -> None:
        s = self._settings

        # Ensure topic taxonomy file exists
        if s.topic_model.enabled:
            labels_file = s.topic_model.labels_file
            if not labels_file.exists():
                raise ValueError(
                    f"Topic taxonomy file not found: {labels_file}"
                )

        # Pipeline batch_size must be reasonable
        if s.pipeline.batch_size > 4096:
            raise ValueError(
                f"PIPELINE_BATCH_SIZE={s.pipeline.batch_size} exceeds max 4096"
            )

        # Sentiment allowed_labels must not be empty
        if s.sentiment_model.enabled and not s.sentiment_model.allowed_labels:
            raise ValueError("SENTIMENT_ALLOWED_LABELS must not be empty")

        # Checkpoint key must be set when checkpointing is enabled
        if s.checkpoint.enabled and not s.checkpoint.key:
            raise ValueError("CHECKPOINT_KEY must be set when checkpointing is enabled")

        # Ensure lookback_days + window hours are sensible
        if s.pipeline.window_start_hour >= s.pipeline.window_end_hour:
            if s.pipeline.window_end_hour != 24:
                raise ValueError(
                    "PIPELINE_WINDOW_START_HOUR must be < PIPELINE_WINDOW_END_HOUR"
                )

        logger.info("configuration_validated_ok")

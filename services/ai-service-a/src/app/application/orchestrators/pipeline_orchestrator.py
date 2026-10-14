"""
PipelineOrchestrator — application layer coordinator.

Owns the per-batch loop:
  fetch → sanitize → normalize → process → persist (update + checkpoint, one TX)

The orchestrator is the single place that wires domain services with infrastructure.
It does NOT contain business logic — that belongs in domain services.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.app.domain.ports import (
    CheckpointValue,
    CommentRepositoryPort,
    CheckpointRepositoryPort,
    EnrichmentUpdate,
    NormalizerPort,
    TopicDailyRecord,
    TopicTrackingRepositoryPort,
)
from src.app.domain.services.process_comments import (
    CommentInput,
    CommentOutput,
    ProcessCommentsService,
    ProcessResult,
    TopicSummary,
)
from src.app.infrastructure.config.settings import PipelineSettings, CheckpointSettings
from src.app.infrastructure.db.repositories import UnitOfWork
from src.app.infrastructure.security.input_sanitizer import bulk_sanitize

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass
class BatchResult:
    batch_number: int
    fetched: int = 0
    sanitized_rejected: int = 0
    processed: int = 0
    updated: int = 0
    skipped_empty: int = 0
    errors: int = 0
    last_comment_id: str = "0"


@dataclass
class RunResult:
    run_date: datetime
    total_batches: int = 0
    total_processed: int = 0
    total_updated: int = 0
    total_errors: int = 0
    total_rejected: int = 0
    status: str = "pending"
    error_message: Optional[str] = None
    batch_results: list[BatchResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class PipelineOrchestrator:

    def __init__(
        self,
        *,
        unit_of_work_factory,       # callable() -> UnitOfWork
        comment_repo_factory,        # callable(session) -> CommentRepositoryPort
        checkpoint_repo_factory,     # callable(session) -> CheckpointRepositoryPort
        topic_tracking_repo_factory,  # callable(session) -> TopicTrackingRepositoryPort
        normalizer: NormalizerPort,
        process_service: ProcessCommentsService,
        pipeline_settings: PipelineSettings,
        checkpoint_settings: CheckpointSettings,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._comment_repo_factory = comment_repo_factory
        self._checkpoint_repo_factory = checkpoint_repo_factory
        self._topic_tracking_repo_factory = topic_tracking_repo_factory
        self._normalizer = normalizer
        self._service = process_service
        self._pipeline_cfg = pipeline_settings
        self._checkpoint_cfg = checkpoint_settings

    # ------------------------------------------------------------------
    def run(
        self,
        window_start: datetime,
        window_end: datetime,
        correlation_id: str = "",
    ) -> RunResult:
        result = RunResult(run_date=datetime.now(timezone.utc))
        cfg = self._pipeline_cfg
        ckpt_cfg = self._checkpoint_cfg

        logger.info(
            "pipeline_run_start",
            extra={
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "correlation_id": correlation_id,
            },
        )

        # Load checkpoint (read-only session)
        last_comment_id = self._load_checkpoint()

        # Accumulate topic summaries across all batches for daily tracking
        accumulated_topics: dict[str, dict] = {}  # topic -> {count, pos, neu, neg}

        batch_num = 0
        max_batches = cfg.max_batches_per_run or float("inf")

        while batch_num < max_batches:
            batch_num += 1
            batch_res = BatchResult(batch_number=batch_num)

            try:
                # ---- Fetch ----
                with self._uow_factory() as uow:
                    comment_repo = self._comment_repo_factory(uow.session)
                    checkpoint_repo = self._checkpoint_repo_factory(uow.session)

                    records = comment_repo.fetch_batch(
                        window_start=window_start,
                        window_end=window_end,
                        last_comment_id=last_comment_id,
                        batch_size=cfg.batch_size,
                        process_only_unclassified=cfg.process_only_unclassified,
                        ignore_date_window=cfg.ignore_date_window,
                    )

                    if not records:
                        logger.info(
                            "pipeline_no_more_records",
                            extra={"batch": batch_num, "last_comment_id": last_comment_id},
                        )
                        result.status = "completed"
                        break

                    batch_res.fetched = len(records)

                    # ---- Sanitize inputs ----
                    raw_texts = [r.text_content for r in records]
                    san_results, rejected_idxs = bulk_sanitize(
                        raw_texts,
                        max_length=2000,
                    )
                    batch_res.sanitized_rejected = len(rejected_idxs)

                    if rejected_idxs:
                        logger.warning(
                            "sanitizer_rejected_comments",
                            extra={
                                "count": len(rejected_idxs),
                                "comment_ids": [records[i].comment_id for i in rejected_idxs],
                            },
                        )

                    # ---- Normalize + build CommentInput (in-memory) ----
                    comment_inputs: list[CommentInput] = []
                    for i, record in enumerate(records):
                        if i in set(rejected_idxs):
                            batch_res.skipped_empty += 1
                            continue
                        normalized = self._normalizer.normalize(san_results[i].sanitized_text)
                        if not normalized.strip():
                            batch_res.skipped_empty += 1
                            continue
                        comment_inputs.append(
                            CommentInput(
                                comment_id=record.comment_id,
                                raw_text=record.text_content,   # kept for audit
                                normalized_text=normalized,
                                source=record.source,
                                created_at=record.created_at.isoformat(),
                            )
                        )

                    if not comment_inputs:
                        # Whole batch was empty/rejected — advance checkpoint and continue
                        last_comment_id = max(r.comment_id for r in records)
                        batch_res.last_comment_id = last_comment_id
                        result.batch_results.append(batch_res)
                        continue

                    # ---- Process (topic + sentiment) ----
                    process_result: ProcessResult = self._service.process_comments(comment_inputs)
                    outputs: list[CommentOutput] = process_result.enriched_comments
                    batch_res.processed = len(outputs)

                    if process_result.topic_summary:
                        logger.info(
                            "batch_topic_summary",
                            extra={
                                "batch": batch_num,
                                "summary": [
                                    {
                                        "topic": ts.topic,
                                        "total": ts.total_comments,
                                        "distribution": ts.sentiment_distribution,
                                    }
                                    for ts in process_result.topic_summary
                                ],
                            },
                        )

                    # ---- Count errors (fallback usage = degraded accuracy) ----
                    for out in outputs:
                        if (
                            out.fallback_used
                            and out.sentiment_confidence is not None
                            and out.sentiment_confidence == 0.0
                        ):
                            batch_res.errors += 1

                    # ---- Check error rate threshold ----
                    error_rate = batch_res.errors / max(len(outputs), 1)
                    if error_rate > cfg.max_error_rate:
                        logger.error(
                            "pipeline_error_rate_exceeded",
                            extra={
                                "error_rate": round(error_rate, 4),
                                "threshold": cfg.max_error_rate,
                                "batch": batch_num,
                            },
                        )
                        result.status = "failed"
                        result.error_message = (
                            f"Batch {batch_num} error rate {error_rate:.2%} exceeds threshold"
                        )
                        return result

                    # ---- Accumulate topic tracking ----
                    for ts in process_result.topic_summary:
                        if ts.topic not in accumulated_topics:
                            accumulated_topics[ts.topic] = {
                                "count": 0, "positive": 0.0, "neutral": 0.0, "negative": 0.0,
                                "total_for_pct": 0,
                            }
                        acc = accumulated_topics[ts.topic]
                        acc["count"] += ts.total_comments
                        acc["total_for_pct"] += ts.total_comments
                        # Weighted accumulation of sentiments
                        acc["positive"] += ts.sentiment_distribution.get("positive", 0.0) * ts.total_comments
                        acc["neutral"] += ts.sentiment_distribution.get("neutral", 0.0) * ts.total_comments
                        acc["negative"] += ts.sentiment_distribution.get("negative", 0.0) * ts.total_comments

                    # ---- Persist (update + checkpoint + tracking — ONE transaction) ----
                    enrichment_updates = [
                        EnrichmentUpdate(
                            comment_id=out.comment_id,
                            topic=out.topic,
                            sentiment=out.sentiment,
                            cluster_id=out.cluster_id,
                            topic_label=out.topic_label,
                            fallback_used=out.fallback_used,
                        )
                        for out in outputs
                    ]
                    updated = comment_repo.update_enrichment_batch(enrichment_updates)
                    batch_res.updated = updated

                    new_last_id = max(out.comment_id for out in outputs)
                    batch_res.last_comment_id = new_last_id

                    if ckpt_cfg.enabled and ckpt_cfg.save_every_batch:
                        checkpoint_repo.save(
                            CheckpointValue(
                                key=ckpt_cfg.key,
                                last_comment_id=new_last_id,
                                last_run_at=datetime.now(timezone.utc),
                                last_window_start=window_start,
                                last_window_end=window_end,
                            )
                        )

                    uow.commit()   # <-- single commit: updates + checkpoint

                    last_comment_id = new_last_id

                    logger.info(
                        "batch_completed",
                        extra={
                            "batch": batch_num,
                            "fetched": batch_res.fetched,
                            "processed": batch_res.processed,
                            "updated": batch_res.updated,
                            "errors": batch_res.errors,
                            "last_comment_id": last_comment_id,
                        },
                    )

            except Exception as exc:
                logger.error(
                    "batch_fatal_error",
                    exc_info=exc,
                    extra={"batch": batch_num},
                )
                result.status = "failed"
                result.error_message = str(exc)
                return result

            result.total_batches += 1
            result.total_processed += batch_res.processed
            result.total_updated += batch_res.updated
            result.total_errors += batch_res.errors
            result.total_rejected += batch_res.sanitized_rejected
            result.batch_results.append(batch_res)

        if result.status == "pending":
            result.status = "completed"

        # ---- Persist aggregated topic daily tracking ----
        if accumulated_topics and result.status == "completed":
            self._persist_topic_tracking(accumulated_topics, window_start)

        logger.info(
            "pipeline_run_complete",
            extra={
                "status": result.status,
                "total_batches": result.total_batches,
                "total_processed": result.total_processed,
                "total_updated": result.total_updated,
                "total_errors": result.total_errors,
            },
        )
        return result

    # ------------------------------------------------------------------
    def _persist_topic_tracking(
        self, accumulated: dict[str, dict], window_start: datetime
    ) -> None:
        """Persist accumulated topic summaries to topic_daily_tracking table."""
        run_date = window_start.date() if hasattr(window_start, 'date') else window_start

        records: list[TopicDailyRecord] = []
        for topic, acc in accumulated.items():
            total = acc["total_for_pct"]
            if total == 0:
                continue
            records.append(
                TopicDailyRecord(
                    run_date=run_date,
                    topic=topic,
                    comment_count=acc["count"],
                    positive_pct=round(acc["positive"] / total, 2),
                    neutral_pct=round(acc["neutral"] / total, 2),
                    negative_pct=round(acc["negative"] / total, 2),
                )
            )

        if not records:
            return

        try:
            with self._uow_factory() as uow:
                tracking_repo = self._topic_tracking_repo_factory(uow.session)
                tracking_repo.upsert_daily_tracking(records)
                uow.commit()
            logger.info(
                "topic_daily_tracking_persisted",
                extra={"topics_count": len(records), "run_date": str(run_date)},
            )
        except Exception as exc:
            logger.error("topic_daily_tracking_persist_failed", exc_info=exc)

    # ------------------------------------------------------------------
    def _load_checkpoint(self) -> str:
        """Returns last_comment_id or '0' if no checkpoint exists."""
        try:
            with self._uow_factory() as uow:
                repo = self._checkpoint_repo_factory(uow.session)
                ckpt = repo.load(self._checkpoint_cfg.key)
                if ckpt:
                    logger.info(
                        "checkpoint_loaded",
                        extra={
                            "key": ckpt.key,
                            "last_comment_id": ckpt.last_comment_id,
                        },
                    )
                    return ckpt.last_comment_id
                logger.info("checkpoint_not_found_starting_from_zero")
                return "0"
        except Exception as exc:
            if self._checkpoint_cfg.strict_mode:
                raise RuntimeError(f"Checkpoint load failed in strict mode: {exc}") from exc
            logger.warning("checkpoint_load_failed_using_zero", exc_info=exc)
            return "0"

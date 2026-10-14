"""
bootstrap.py — application dependency wiring.

Call bootstrap() once at process startup.
All components receive injected dependencies — no service locators in business code.

NEW ARCHITECTURE:
  - Sentiment classifier (kept)
  - Topic clustering adapter (new — embeds + clusters)
  - LLM topic labeler (new — Gemma 4B via localhost API)
  - Topic classifier (kept as FALLBACK when LLM is unavailable)

Security: validates configuration, loads models, warms up inference before accepting traffic.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from src.app.application.orchestrators.pipeline_orchestrator import PipelineOrchestrator
from src.app.application.use_cases import (
    RunDailyPipelineUseCase,
    ReprocessDateRangeUseCase,
    ValidateConfigurationUseCase,
)
from src.app.domain.services.process_comments import ProcessCommentsService
from src.app.infrastructure.config.settings import Settings, get_settings
from src.app.infrastructure.db.repositories import (
    PostgresCommentRepository,
    PostgresCheckpointRepository,
    PostgresTopicTrackingRepository,
    UnitOfWork,
    create_db_engine,
)
from src.app.infrastructure.ml.providers.hf_topic_classifier import HFTopicClassifier
from src.app.infrastructure.ml.providers.hf_sentiment_classifier import HFSentimentClassifier
from src.app.infrastructure.ml.providers.topic_clustering import TopicClusteringAdapter
from src.app.infrastructure.ml.providers.llm_topic_labeler import LLMTopicLabeler
from src.app.infrastructure.normalization.social_text_normalizer import SocialTextNormalizer
from src.app.infrastructure.observability.logging import configure_logging
from src.app.infrastructure.word_cloud.dictionary_matcher import DictionaryMatcher
from src.app.infrastructure.word_cloud.tfidf_extractor import TfIdfExtractor
from src.app.application.use_cases.word_cloud_use_case import RefreshWordCloudUseCase

logger = logging.getLogger(__name__)


@dataclass
class AppContainer:
    """Single object holding all wired application components."""
    settings: Settings
    engine: Engine
    session_factory: sessionmaker
    orchestrator: PipelineOrchestrator
    run_daily_use_case: RunDailyPipelineUseCase
    reprocess_date_range_use_case: ReprocessDateRangeUseCase
    validate_config_use_case: ValidateConfigurationUseCase
    sentiment_classifier: HFSentimentClassifier
    topic_classifier_fallback: HFTopicClassifier
    topic_clustering: TopicClusteringAdapter
    topic_labeler: LLMTopicLabeler
    refresh_word_cloud_use_case: RefreshWordCloudUseCase


def bootstrap() -> AppContainer:
    """
    Wires the entire application.
    Raises SystemExit(1) on any startup failure — fail-fast by design.
    """
    # 1. Load and validate all settings (raises ValueError on bad config)
    try:
        settings = get_settings()
    except Exception as exc:
        print(f"[FATAL] Configuration validation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # 2. Configure structured logging first (so all subsequent logs are formatted)
    configure_logging(settings)

    logger.info("bootstrap_start", extra={"env": settings.app.env})

    # 3. Validate configuration cross-checks
    try:
        ValidateConfigurationUseCase(settings).execute()
    except Exception as exc:
        logger.critical("config_validation_failed", exc_info=exc)
        sys.exit(1)

    # 4. Load topic taxonomy (still needed for fallback classifier validation)
    taxonomy_labels = _load_taxonomy(settings.topic_model.labels_file)

    # 5. Create DB engine + session factory
    engine = create_db_engine(settings.database)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def uow_factory() -> UnitOfWork:
        return UnitOfWork(session_factory)

    # 6. Create sentiment classifier (primary — always used)
    sentiment_clf = HFSentimentClassifier(settings.sentiment_model)

    # 7. Create topic classifier (FALLBACK — used when LLM is unavailable)
    topic_clf_fallback = HFTopicClassifier(settings.topic_model)

    # 8. Create topic clustering adapter (new — embeds + clusters)
    topic_clustering = TopicClusteringAdapter(
        embedding_settings=settings.embedding,
        clustering_settings=settings.clustering,
    )

    # 9. Create LLM topic labeler (new — Gemma 4B via localhost API)
    topic_labeler = LLMTopicLabeler(settings.llm)

    # 10. Load + warm up models (blocking — must complete before accepting traffic)
    if settings.sentiment_model.warmup:
        try:
            sentiment_clf.warmup()
        except Exception as exc:
            logger.critical("sentiment_model_load_failed", exc_info=exc)
            sys.exit(1)

    if settings.topic_model.warmup:
        try:
            topic_clf_fallback.warmup()
            logger.info("topic_fallback_model_loaded")
        except Exception as exc:
            logger.warning(
                "topic_fallback_model_load_failed_continuing",
                exc_info=exc,
            )
            # Non-fatal: LLM path is primary, fallback model failure is degraded but not dead

    # 11. Create domain service (NEW architecture)
    process_service = ProcessCommentsService(
        sentiment_classifier=sentiment_clf,
        topic_clustering=topic_clustering,
        topic_labeler=topic_labeler,
        topic_classifier_fallback=topic_clf_fallback,
        sentiment_fallback=settings.sentiment_model.fallback_label,
        topic_fallback=settings.topic_model.output_label_fallback,
    )

    # 12. Create normalizer
    normalizer = SocialTextNormalizer(settings.normalization)

    # 13. Create orchestrator
    orchestrator = PipelineOrchestrator(
        unit_of_work_factory=uow_factory,
        comment_repo_factory=lambda session: PostgresCommentRepository(session),
        checkpoint_repo_factory=lambda session: PostgresCheckpointRepository(session),
        topic_tracking_repo_factory=lambda session: PostgresTopicTrackingRepository(session),
        normalizer=normalizer,
        process_service=process_service,
        pipeline_settings=settings.pipeline,
        checkpoint_settings=settings.checkpoint,
    )

    # 14. Create use cases
    run_daily = RunDailyPipelineUseCase(orchestrator, settings)
    reprocess_dr = ReprocessDateRangeUseCase(orchestrator, settings)
    validate_cfg = ValidateConfigurationUseCase(settings)

    # 15. Word cloud strategies + use case
    wc_strategies = []
    if settings.word_cloud.enabled:
        dict_matcher = DictionaryMatcher(settings.word_cloud.dictionary_path)
        tfidf_ext = TfIdfExtractor(
            top_n=settings.word_cloud.tfidf_top_n,
            min_frequency=settings.word_cloud.min_frequency,
            curated_words=set(dict_matcher._canonical_to_category.keys()),
        )
        wc_strategies = [dict_matcher, tfidf_ext]

    wc_variant_map = dict_matcher._variant_to_canonical if settings.word_cloud.enabled else {}
    refresh_word_cloud = RefreshWordCloudUseCase(
        unit_of_work_factory=uow_factory,
        strategies=wc_strategies,
        settings=settings.word_cloud,
        variant_to_canonical=wc_variant_map,
    )

    logger.info("bootstrap_complete", extra={
        "llm_enabled": settings.llm.enabled,
        "llm_model": settings.llm.model_name,
        "embedding_model": settings.embedding.model_name,
        "word_cloud_enabled": settings.word_cloud.enabled,
    })

    return AppContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        orchestrator=orchestrator,
        run_daily_use_case=run_daily,
        reprocess_date_range_use_case=reprocess_dr,
        validate_config_use_case=validate_cfg,
        sentiment_classifier=sentiment_clf,
        topic_classifier_fallback=topic_clf_fallback,
        topic_clustering=topic_clustering,
        topic_labeler=topic_labeler,
        refresh_word_cloud_use_case=refresh_word_cloud,
    )


def _load_taxonomy(labels_file: Path) -> list[str]:
    """Load topic labels from YAML. Validates against injection."""
    try:
        with open(labels_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)   # safe_load prevents arbitrary Python execution
        labels = data.get("labels", [])
        if not labels:
            raise ValueError("topic_taxonomy.yaml contains no labels")
        # Sanitize: labels must be non-empty strings (preserve original case for model matching)
        clean = []
        for lbl in labels:
            s = str(lbl).strip()
            if not s or len(s) > 256:
                continue
            clean.append(s)
        if not clean:
            raise ValueError("No valid labels found in topic_taxonomy.yaml")
        return clean
    except FileNotFoundError:
        logger.critical("taxonomy_file_not_found", extra={"path": str(labels_file)})
        sys.exit(1)

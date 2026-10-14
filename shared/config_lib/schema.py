"""
schema.py — Pydantic models for ALL configuration consumed from Consul KV.

Every config payload is wrapped in a ConfigEnvelope with version + timestamp.
Settings are split into HOT-RELOADABLE vs RESTART-REQUIRED categories.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class ConfigCategory(str, Enum):
    HOT_RELOAD = "hot_reload"
    RESTART_REQUIRED = "restart_required"


# ---------------------------------------------------------------------------
# Envelope — wraps every config payload
# ---------------------------------------------------------------------------
class ConfigEnvelope(BaseModel):
    """Every Consul KV payload MUST contain version + updated_at."""
    version: int = Field(ge=1, description="Monotonically increasing config version")
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    settings: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Global config (config/global/*)
# ---------------------------------------------------------------------------
class GlobalConfig(BaseModel):
    """Settings shared across ALL services."""
    version: int = 1
    maintenance_mode: bool = False
    logging_level: str = "INFO"


# ---------------------------------------------------------------------------
# AI Service A — Topic Extraction Pipeline
# ---------------------------------------------------------------------------
class AIServiceAThresholds(BaseModel):
    """HOT-RELOADABLE thresholds for AI Service A."""
    sentiment_confidence_min: float = Field(0.5, ge=0.0, le=1.0)
    cluster_merge_similarity: float = Field(0.85, ge=0.0, le=1.0)
    topic_confidence_min: float = Field(0.3, ge=0.0, le=1.0)
    max_clusters: int = Field(20, ge=2, le=100)
    min_cluster_size: int = Field(2, ge=1, le=50)
    top_k_representatives: int = Field(15, ge=1, le=50)


class AIServiceAModel(BaseModel):
    """RESTART-REQUIRED model settings for AI Service A."""
    embedding_model_path: str = "/app/models/dziri_topic_classifier_v2"
    sentiment_model_path: str = "/app/models/ensia-emobert-training"
    topic_model_path: str = "/app/models/dziri_topic_classifier_v2"
    embedding_device: str = "auto"
    embedding_batch_size: int = 64
    embedding_max_length: int = 512


class AIServiceAWorkers(BaseModel):
    """RESTART-REQUIRED worker pool settings."""
    batch_size: int = Field(256, ge=1, le=2048)
    max_batches: int = Field(100, ge=1, le=10000)


class AIServiceARuntime(BaseModel):
    """HOT-RELOADABLE runtime settings."""
    llm_enabled: bool = True
    llm_api_base_url: str = "http://host.docker.internal:8000"
    llm_api_format: str = "openai"
    llm_model_name: str = "gemma-4b"
    llm_max_tokens: int = 100
    llm_temperature: float = 0.1
    llm_retry_attempts: int = 3
    llm_retry_delay_seconds: float = 2.0
    fallback_topic_label: str = "other"
    fallback_sentiment_label: str = "neutral"
    process_only_unclassified: bool = True
    umap_n_components: int = 15
    umap_n_neighbors: int = 30
    umap_min_dist: float = 0.0
    umap_metric: str = "cosine"
    # ── Scheduler (HOT-RELOADABLE — APScheduler reschedules live) ──────────
    schedule_cron: str = Field(
        "0 1 * * *",
        description="Cron expression for the daily pipeline run (Africa/Algiers). "
                    "Format: 'minute hour day month weekday'. "
                    "Default '0 1 * * *' = every day at 01:00.",
    )
    run_on_startup: bool = Field(
        True,
        description="Run the pipeline immediately when the container starts, "
                    "in addition to the scheduled cron run.",
    )
    lookback_days: int = Field(
        1,
        ge=1,
        le=90,
        description="Number of local days included in each enrichment run.",
    )


class AIServiceAWordCloud(BaseModel):
    """HOT-RELOADABLE word-cloud extraction settings."""
    max_words: int = Field(200, ge=10, le=1000)
    min_frequency: int = Field(3, ge=1, le=1000)


class AIServiceAConfig(BaseModel):
    """Complete configuration for AI Service A."""
    thresholds: AIServiceAThresholds = Field(default_factory=AIServiceAThresholds)
    model: AIServiceAModel = Field(default_factory=AIServiceAModel)
    workers: AIServiceAWorkers = Field(default_factory=AIServiceAWorkers)
    runtime: AIServiceARuntime = Field(default_factory=AIServiceARuntime)
    word_cloud: AIServiceAWordCloud = Field(default_factory=AIServiceAWordCloud)


# ---------------------------------------------------------------------------
# AI Service B — Meta Scraper
# ---------------------------------------------------------------------------
class AIServiceBThresholds(BaseModel):
    """HOT-RELOADABLE scraper thresholds."""
    rate_limit_threshold: float = Field(0.85, ge=0.1, le=1.0)
    like_skip_threshold: float = Field(0.90, ge=0.1, le=1.0)
    max_post_age_h: int = Field(24, ge=1, le=168)
    max_active_posts: int = Field(15, ge=1, le=500)
    scrape_replies: bool = False
    reply_max_depth: int = Field(5, ge=1, le=10)


class AIServiceBScheduler(BaseModel):
    """RESTART-REQUIRED scheduler settings."""
    scraper_interval_h: int = Field(4, ge=1, le=24)
    scraper_stagger_seconds: int = Field(30, ge=0, le=600)
    job_timeout_m: int = Field(10, ge=1, le=60)


class AIServiceBRuntime(BaseModel):
    """HOT-RELOADABLE runtime settings."""
    semaphore_limit: int = Field(10, ge=1, le=50)
    retry_max_attempts: int = Field(3, ge=1, le=10)
    batch_like_size: int = Field(50, ge=1, le=50)


class AIServiceBConfig(BaseModel):
    """Complete configuration for AI Service B."""
    thresholds: AIServiceBThresholds = Field(default_factory=AIServiceBThresholds)
    scheduler: AIServiceBScheduler = Field(default_factory=AIServiceBScheduler)
    runtime: AIServiceBRuntime = Field(default_factory=AIServiceBRuntime)


# ---------------------------------------------------------------------------
# Reply Service — Group Reply (engagement plane)
# ---------------------------------------------------------------------------
class ReplyWindow(BaseModel):
    """HOT-RELOADABLE scheduling window."""
    hours: int = Field(24, ge=1, le=168)


class ReplyCapacity(BaseModel):
    """HOT-RELOADABLE per-page capacity / back-pressure."""
    daily_per_page: int = Field(1000, ge=1, le=100000)
    max_backlog_days: int = Field(3, ge=1, le=30)


class ReplyCoordination(BaseModel):
    """HOT-RELOADABLE scrape/reply rate coordination (R6)."""
    reply_usage_ceiling: float = Field(60.0, ge=1.0, le=100.0)
    reply_min_per_hour: int = Field(30, ge=0, le=5000)


class ReplyPacing(BaseModel):
    """HOT-RELOADABLE per-page send pacing."""
    reply_max_per_minute: int = Field(20, ge=1, le=600)


class ReplyDispatch(BaseModel):
    """Dispatcher cadence (tick HOT, pool size RESTART-REQUIRED)."""
    tick_seconds: int = Field(15, ge=1, le=300)
    worker_pool_size: int = Field(12, ge=1, le=140)


class ReplySend(BaseModel):
    """HOT-RELOADABLE send retry / reclaim."""
    max_attempts: int = Field(5, ge=1, le=20)
    claim_timeout_seconds: int = Field(120, ge=10, le=3600)


class ReplyServiceConfig(BaseModel):
    """Complete configuration for the Reply Service."""
    window: ReplyWindow = Field(default_factory=ReplyWindow)
    capacity: ReplyCapacity = Field(default_factory=ReplyCapacity)
    coordination: ReplyCoordination = Field(default_factory=ReplyCoordination)
    pacing: ReplyPacing = Field(default_factory=ReplyPacing)
    dispatch: ReplyDispatch = Field(default_factory=ReplyDispatch)
    send: ReplySend = Field(default_factory=ReplySend)


# ---------------------------------------------------------------------------
# Feedback Service — Label Feedback (human-in-the-loop correction)
# ---------------------------------------------------------------------------
class FeedbackTopic(BaseModel):
    """HOT-RELOADABLE free-text topic rules."""
    max_len: int = Field(80, ge=1, le=512)
    allow_digits_if_not_only: bool = True


class FeedbackRead(BaseModel):
    """HOT-RELOADABLE live-recompute read settings (Pass 2)."""
    recompute_cache_ttl_seconds: int = Field(30, ge=0, le=3600)
    run_boundary_source: str = "job_executions"


class FeedbackExport(BaseModel):
    """HOT-RELOADABLE retraining export."""
    schedule_cron: str = ""  # empty = no scheduled snapshot


class FeedbackSimilarity(BaseModel):
    """HOT-RELOADABLE topic similarity-mapping (production seam)."""
    enabled: bool = False


class FeedbackServiceConfig(BaseModel):
    """Complete configuration for the Feedback Service."""
    topic: FeedbackTopic = Field(default_factory=FeedbackTopic)
    read: FeedbackRead = Field(default_factory=FeedbackRead)
    export: FeedbackExport = Field(default_factory=FeedbackExport)
    similarity: FeedbackSimilarity = Field(default_factory=FeedbackSimilarity)


# ---------------------------------------------------------------------------
# Restart-required key registry
# ---------------------------------------------------------------------------
RESTART_REQUIRED_KEYS: dict[str, set[str]] = {
    "ai-service-a": {
        "model.embedding_model_path",
        "model.sentiment_model_path",
        "model.topic_model_path",
        "model.embedding_device",
        "model.embedding_batch_size",
        "model.embedding_max_length",
        "workers.batch_size",
        "workers.max_batches",
    },
    "ai-service-b": {
        "scheduler.scraper_interval_h",
        "scheduler.scraper_stagger_seconds",
        "scheduler.job_timeout_m",
    },
    "reply-service": {
        "dispatch.worker_pool_size",
    },
    "feedback-service": set(),  # all keys hot-reloadable
}


def is_restart_required(service_name: str, changed_keys: set[str]) -> bool:
    """Check if any of the changed keys require a service restart."""
    restart_keys = RESTART_REQUIRED_KEYS.get(service_name, set())
    return bool(changed_keys & restart_keys)

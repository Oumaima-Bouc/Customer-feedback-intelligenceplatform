"""
Typed, startup-validated settings.
Loaded ONCE at bootstrap; all modules receive injected settings — no os.getenv() in business code.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import AnyUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# APP
# ---------------------------------------------------------------------------
class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    name: str = "comment-enrichment-system"
    env: Literal["development", "staging", "production"] = "production"
    debug: bool = False
    timezone: str = "Africa/Algiers"
    host: str = "0.0.0.0"
    port: int = Field(8080, ge=1024, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "text"] = "json"
    enable_api: bool = True
    enable_metrics: bool = True
    enable_tracing: bool = False
    enable_healthcheck: bool = True
    correlation_id_header: str = "X-Correlation-ID"

    @field_validator("debug")
    @classmethod
    def no_debug_in_production(cls, v: bool, info) -> bool:
        # env not available at field-level validator; checked in model_validator below
        return v

    @model_validator(mode="after")
    def production_debug_guard(self) -> "AppSettings":
        if self.env == "production" and self.debug:
            raise ValueError("APP_DEBUG must be false in production")
        return self


# ---------------------------------------------------------------------------
# SECURITY
# ---------------------------------------------------------------------------
class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    admin_api_key: SecretStr = Field(..., alias="ADMIN_API_KEY")
    secret_redaction_enabled: bool = Field(True, alias="SECRET_REDACTION_ENABLED")
    allow_reprocess_endpoint: bool = Field(False, alias="ALLOW_REPROCESS_ENDPOINT")

    @field_validator("admin_api_key")
    @classmethod
    def api_key_strength(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if raw in ("replace_me", "", "changeme", "secret"):
            raise ValueError("ADMIN_API_KEY is not set to a real value — refusing to start")
        if len(raw) < 32:
            raise ValueError("ADMIN_API_KEY must be at least 32 characters")
        return v


# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------
class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", env_file=".env", extra="ignore")

    host: str = Field("localhost", alias="DB_HOST")
    port: int = Field(5432, ge=1, le=65535)
    name: str = Field("scraper_db", alias="DB_NAME")
    user: str = Field("scraper", alias="DB_USER")
    password: SecretStr = Field(..., alias="DB_PASSWORD")
    ssl_mode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = "disable"
    application_name: str = Field("topic-extraction-pipeline", alias="DB_APPLICATION_NAME")
    pool_size: int = Field(10, ge=1, le=100)
    max_overflow: int = Field(20, ge=0, le=200)
    pool_timeout_seconds: int = Field(30, ge=1)
    pool_recycle_seconds: int = Field(1800, ge=60)
    connect_timeout_seconds: int = Field(10, ge=1)
    statement_timeout_ms: int = Field(60_000, ge=1000)
    lock_timeout_ms: int = Field(10_000, ge=500)

    @field_validator("password")
    @classmethod
    def password_not_empty(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if not raw:
            raise ValueError("DB_PASSWORD must not be empty")
        return v

    @property
    def dsn(self) -> str:
        """Returns a safe DSN string (password redacted for logging)."""
        return (
            f"postgresql+psycopg://{self.user}:***@"
            f"{self.host}:{self.port}/{self.name}"
            f"?sslmode={self.ssl_mode}&application_name={self.application_name}"
            f"&connect_timeout={self.connect_timeout_seconds}"
        )

    @property
    def secret_dsn(self) -> str:
        """Full DSN for SQLAlchemy engine creation — never log this."""
        pw = self.password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.user}:{pw}@"
            f"{self.host}:{self.port}/{self.name}"
            f"?sslmode={self.ssl_mode}&application_name={self.application_name}"
            f"&connect_timeout={self.connect_timeout_seconds}"
        )

    @property
    def plain_dsn(self) -> str:
        """Plain psycopg2-compatible DSN for direct connections (e.g. job tracker)."""
        pw = self.password.get_secret_value()
        return f"host={self.host} port={self.port} dbname={self.name} user={self.user} password={pw}"


# ---------------------------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------------------------
class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIPELINE_", env_file=".env", extra="ignore")

    schedule_cron: str = "0 1 * * *"
    window_timezone: str = "Africa/Algiers"
    lookback_days: int = Field(1, ge=1, le=90)
    window_start_hour: int = Field(0, ge=0, le=23)
    window_end_hour: int = Field(24, ge=1, le=24)
    batch_size: int = Field(256, ge=1, le=4096)
    max_batches_per_run: int = Field(0, ge=0)   # 0 = unlimited
    process_only_unclassified: bool = True
    ignore_date_window: bool = False
    force_reprocess: bool = False
    fail_on_empty_batch: bool = False
    max_error_rate: float = Field(0.10, ge=0.0, le=1.0)
    shutdown_grace_seconds: int = Field(30, ge=0)

    @field_validator("schedule_cron")
    @classmethod
    def valid_cron(cls, v: str) -> str:
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {v!r}")
        return v


# ---------------------------------------------------------------------------
# CHECKPOINTING
# ---------------------------------------------------------------------------
class CheckpointSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHECKPOINT_", env_file=".env", extra="ignore")

    key: str = Field("comments_daily_default", alias="CHECKPOINT_KEY")
    enabled: bool = True
    strict_mode: bool = True
    save_every_batch: bool = True
    reset_on_force_reprocess: bool = False

    @field_validator("key")
    @classmethod
    def key_safe(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\-]{1,128}$", v):
            raise ValueError(f"CHECKPOINT_KEY contains unsafe characters: {v!r}")
        return v


# ---------------------------------------------------------------------------
# NORMALIZATION
# ---------------------------------------------------------------------------
class NormalizationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NORMALIZE_", env_file=".env", extra="ignore")

    enabled: bool = True
    keep_emojis: bool = True
    remove_urls: bool = True
    remove_mentions: bool = False
    remove_hashtags: bool = False
    remove_control_chars: bool = True
    collapse_whitespace: bool = True
    max_text_length: int = Field(2000, ge=1, le=10_000)
    strip_html: bool = True
    unicode_nfkc: bool = True


# ---------------------------------------------------------------------------
# TOPIC MODEL
# ---------------------------------------------------------------------------
class TopicModelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOPIC_MODEL_", env_file=".env", extra="ignore")

    enabled: bool = True
    provider: Literal["huggingface", "onnx"] = "huggingface"
    name: str = Field(..., alias="TOPIC_MODEL_NAME")
    revision: str = "main"
    device: Literal["cpu", "cuda", "mps"] = "cpu"
    batch_size: int = Field(64, ge=1, le=512)
    max_length: int = Field(256, ge=16, le=512)
    cache_dir: Path = Field(Path("/app/models"), alias="TOPIC_MODEL_CACHE_DIR")
    timeout_seconds: int = Field(120, ge=10)
    warmup: bool = True
    labels_file: Path = Field(Path("/app/config/topic_taxonomy.yaml"), alias="TOPIC_LABELS_FILE")
    confidence_min: float = Field(0.0, ge=0.0, le=1.0)
    output_label_fallback: str = "other"

    @field_validator("name")
    @classmethod
    def name_not_placeholder(cls, v: str) -> str:
        if v in ("replace_with_real_topic_model", "", "none"):
            raise ValueError("TOPIC_MODEL_NAME must be a real HuggingFace model name or local path")
        return v

    @field_validator("revision")
    @classmethod
    def safe_revision(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\-\.\/]{1,200}$", v):
            raise ValueError(f"TOPIC_MODEL_REVISION contains unsafe characters: {v!r}")
        return v


# ---------------------------------------------------------------------------
# SENTIMENT MODEL
# ---------------------------------------------------------------------------
class SentimentModelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENTIMENT_MODEL_", env_file=".env", extra="ignore")

    enabled: bool = True
    provider: Literal["huggingface", "onnx"] = "huggingface"
    name: str = Field(..., alias="SENTIMENT_MODEL_NAME")
    revision: str = "main"
    device: Literal["cpu", "cuda", "mps"] = "cpu"
    batch_size: int = Field(64, ge=1, le=512)
    max_length: int = Field(256, ge=16, le=512)
    cache_dir: Path = Field(Path("/app/models"), alias="SENTIMENT_MODEL_CACHE_DIR")
    timeout_seconds: int = Field(120, ge=10)
    warmup: bool = True
    allowed_labels: list[str] = ["positive", "neutral", "negative"]
    fallback_label: str = "neutral"

    @field_validator("name")
    @classmethod
    def name_not_placeholder(cls, v: str) -> str:
        if v in ("replace_with_real_sentiment_model", "", "none"):
            raise ValueError("SENTIMENT_MODEL_NAME must be a real HuggingFace model name or local path")
        return v

    @field_validator("allowed_labels", mode="before")
    @classmethod
    def parse_labels(cls, v) -> list[str]:
        if isinstance(v, str):
            return [lbl.strip() for lbl in v.split(",") if lbl.strip()]
        return v


# ---------------------------------------------------------------------------
# LLM TOPIC LABELING (Gemma 3 4B via Ollama — lm-service container)
# ---------------------------------------------------------------------------
class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_", env_file=".env", extra="ignore", protected_namespaces=("settings_",))

    enabled: bool = True
    # api_format="openai" — Ollama supports the OpenAI /v1/chat/completions API
    api_format: Literal["openai", "ollama", "query_param", "custom"] = "openai"
    # Default URL points at the lm-service Docker container (Ollama port 11434).
    # Override with LLM_API_BASE_URL env var for local development.
    api_base_url: str = Field("http://lm-service:11434", alias="LLM_API_BASE_URL")
    api_endpoint: str = Field("/v1/chat/completions", alias="LLM_API_ENDPOINT")
    api_key: str = Field("", alias="LLM_API_KEY")   # Ollama needs no API key
    # Model name in Ollama registry format ("gemma3:4b", not "gemma-3-4b-it")
    model_name: str = Field("gemma3:4b", alias="LLM_MODEL_NAME")
    max_tokens: int = Field(150, ge=10, le=2000)
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    # CPU inference for Gemma 3 4B can take 10-90 s per request depending on hardware.
    # 300 s gives generous headroom even for slow machines.
    timeout_seconds: int = Field(300, ge=5)
    retry_attempts: int = Field(2, ge=1, le=10)
    retry_delay_seconds: float = Field(2.0, ge=0.5)
    merge_clusters: bool = True


# ---------------------------------------------------------------------------
# EMBEDDING (for topic clustering)
# ---------------------------------------------------------------------------
class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", env_file=".env", extra="ignore", protected_namespaces=("settings_",))

    model_name: str = Field("alger-ia/dziribert", alias="EMBEDDING_MODEL")
    batch_size: int = Field(64, ge=1, le=512)
    max_length: int = Field(128, ge=16, le=512)
    device: Literal["cpu", "cuda", "mps", "auto"] = "auto"


# ---------------------------------------------------------------------------
# CLUSTERING
# ---------------------------------------------------------------------------
class ClusteringSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLUSTER_", env_file=".env", extra="ignore")

    n_clusters: Optional[int] = None  # None = auto-detect via silhouette
    k_range_min: int = Field(5, ge=2)
    k_range_max: int = Field(25, ge=3)
    top_k_representatives: int = Field(15, ge=1, le=50)
    merge_similarity_threshold: float = Field(0.88, ge=0.5, le=1.0)
    umap_n_components: int = Field(10, ge=2, le=100)
    umap_n_neighbors: int = Field(15, ge=5, le=200)
    umap_min_dist: float = Field(0.0, ge=0.0, le=1.0)
    umap_metric: str = "cosine"
    random_seed: int = Field(42, ge=0)
    min_cluster_size: int = Field(2, ge=1)

    @field_validator("n_clusters", mode="before")
    @classmethod
    def parse_n_clusters(cls, v) -> Optional[int]:
        if v is None or (isinstance(v, str) and v.lower() in ("auto", "", "none")):
            return None
        return int(v)


# ---------------------------------------------------------------------------
# WORD CLOUD
# ---------------------------------------------------------------------------
class WordCloudSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORDCLOUD_", env_file=".env", extra="ignore")

    enabled: bool = True
    dictionary_path: Path = Field(Path("/app/config/words.yaml"), alias="WORDCLOUD_DICTIONARY_PATH")
    min_frequency: int = Field(3, ge=1, alias="WORDCLOUD_MIN_FREQUENCY")
    tfidf_top_n: int = Field(50, ge=5, le=500, alias="WORDCLOUD_TFIDF_TOP_N")
    max_words: int = Field(200, ge=10, le=1000, alias="WORDCLOUD_MAX_WORDS")
    lookback_hours: int = Field(24, ge=1, le=168, alias="WORDCLOUD_LOOKBACK_HOURS")


# ---------------------------------------------------------------------------
# OBSERVABILITY
# ---------------------------------------------------------------------------
class ObservabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    metrics_namespace: str = Field("comment_pipeline", alias="METRICS_NAMESPACE")
    metrics_port: int = Field(9090, ge=1024, le=65535, alias="METRICS_PORT")
    otel_service_name: str = Field("comment-enrichment-system", alias="OTEL_SERVICE_NAME")
    otel_exporter_otlp_endpoint: Optional[str] = Field(None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_exporter_otlp_headers: Optional[str] = Field(None, alias="OTEL_EXPORTER_OTLP_HEADERS")
    trace_sample_ratio: float = Field(0.05, ge=0.0, le=1.0, alias="TRACE_SAMPLE_RATIO")


# ---------------------------------------------------------------------------
# FEATURE FLAGS
# ---------------------------------------------------------------------------
class FeatureFlagSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FEATURE_", env_file=".env", extra="ignore")

    enable_admin_runs: bool = True
    write_legacy_tables: bool = False
    store_model_version_in_logs: bool = True
    allow_date_range_reprocess: bool = True
    allow_id_range_reprocess: bool = True


# ---------------------------------------------------------------------------
# ROOT SETTINGS (aggregated)
# ---------------------------------------------------------------------------
class Settings:
    """Aggregate root — single object injected throughout the app."""

    def __init__(self) -> None:
        self.app = AppSettings()
        self.security = SecuritySettings()
        self.database = DatabaseSettings()
        self.pipeline = PipelineSettings()
        self.checkpoint = CheckpointSettings()
        self.normalization = NormalizationSettings()
        self.topic_model = TopicModelSettings()
        self.sentiment_model = SentimentModelSettings()
        self.llm = LLMSettings()
        self.embedding = EmbeddingSettings()
        self.clustering = ClusteringSettings()
        self.observability = ObservabilitySettings()
        self.features = FeatureFlagSettings()
        self.word_cloud = WordCloudSettings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Singleton loader — raises ValueError at startup on any misconfiguration.
    Call this once in bootstrap.py; never call os.getenv() in domain code.
    """
    return Settings()

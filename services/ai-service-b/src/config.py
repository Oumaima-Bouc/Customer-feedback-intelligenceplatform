"""
C1 - Infrastructure & Configuration
config.py
Single source of truth for all environment variables.
Process exits with a clear message if any required var is missing or malformed.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All environment variables consumed by the scraper system.
    Pydantic validates types and constraints at process startup.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Meta API --
    meta_page_id: str = Field(..., description="Target Facebook page numeric ID")
    meta_access_token: str = Field(..., description="Long-lived Page Token")
    graph_api_version: str = Field("v25.0", description="Meta Graph API version, e.g. v25.0")

    # -- Database --
    database_url: str = Field(
        ...,
        description="asyncpg DSN: postgresql://user:pass@host:port/dbname",
    )
    db_pool_min: int = Field(2, ge=1, le=20)
    db_pool_max: int = Field(10, ge=1, le=100)

    # -- Scheduler --
    scraper_interval_h: int = Field(4, ge=1, le=24, description="Run interval in hours")
    scraper_stagger_seconds: int = Field(30, ge=0, le=600, description="Seconds between consecutive source scrapes")
    job_timeout_m: int = Field(10, ge=1, le=60, description="Max job runtime in minutes")
    max_post_age_h: int = Field(24, ge=1, le=168, description="Active post window in hours")

    # -- Scraper behavior --
    scrape_replies: bool = Field(False, description="Enable reply ingestion (MVP: off)")
    reply_max_depth: int = Field(5, ge=1, le=10)
    max_active_posts: int = Field(15, ge=1, le=500)
    retry_max_attempts: int = Field(3, ge=1, le=10)
    semaphore_limit: int = Field(10, ge=1, le=50, description="Max concurrent post workers")

    # -- Rate limiting --
    rate_limit_threshold: float = Field(
        0.85, ge=0.1, le=1.0, description="Quota % that triggers pause (0.0-1.0)"
    )
    batch_like_size: int = Field(50, ge=1, le=50, description="Comment IDs per like batch call")

    # -- Logging --
    log_level: str = Field("INFO", description="DEBUG | INFO | WARNING | ERROR")

    # -- Computed helpers --
    @property
    def graph_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.graph_api_version}"

    @property
    def like_skip_threshold(self) -> float:
        """Above this, C4 skips like-sync entirely (Decision SL-5)."""
        return 0.90

    # -- Validators --
    @field_validator("graph_api_version")
    @classmethod
    def validate_api_version(cls, v: str) -> str:
        if not v.startswith("v") or not v[1:].replace(".", "").isdigit():
            raise ValueError(
                f"GRAPH_API_VERSION must be in format 'vNN.N', got: '{v}'"
            )
        return v

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not (v.startswith("postgresql://") or v.startswith("postgresql+asyncpg://")):
            raise ValueError(
                "DATABASE_URL must start with postgresql:// or postgresql+asyncpg://"
            )
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}, got: '{v}'")
        return upper

    @model_validator(mode="after")
    def validate_pool_sizes(self) -> "Settings":
        if self.db_pool_min > self.db_pool_max:
            raise ValueError(
                f"DB_POOL_MIN ({self.db_pool_min}) must be <= DB_POOL_MAX ({self.db_pool_max})"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns the singleton Settings instance.
    Raises a descriptive ValidationError if any env var is missing or invalid.
    Call once at startup - lru_cache ensures it is only parsed once.
    """
    return Settings()


# Convenience alias used throughout the codebase:
#   from config import settings
settings: Settings = get_settings()
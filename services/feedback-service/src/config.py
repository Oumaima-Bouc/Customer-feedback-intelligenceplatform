"""
Infrastructure & configuration singleton for feedback-service.

Mirrors reply-service: env-driven infra (DATABASE_URL) + runtime tunables that
Consul `config/feedback-service` overwrites at startup / hot-reload. Defaults match
the Consul seed so the service is sane even before Consul is read.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # ── Infra (env) ──
    database_url: str = Field(..., description="postgresql DSN")

    # ── Consul-driven tunables (config/feedback-service) ──
    topic_max_len: int = 80
    topic_allow_digits_if_not_only: bool = True
    read_recompute_cache_ttl_seconds: int = 30
    read_run_boundary_source: str = "job_executions"
    export_schedule_cron: str = ""
    similarity_enabled: bool = False

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not (v.startswith("postgresql://") or v.startswith("postgresql+asyncpg://")):
            raise ValueError("DATABASE_URL must start with postgresql:// or postgresql+asyncpg://")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()

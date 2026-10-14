"""
Infrastructure & configuration singleton for reply-service.

Mirrors the ai-service-b pattern: env-driven infra (DATABASE_URL, GRAPH_API_VERSION)
plus runtime tunables that are overwritten from Consul `config/reply-service` at
startup (and on hot-reload) by entrypoint._apply_config. Defaults here match the
Consul seed so the service is sane even before Consul is read.
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
    database_url: str = Field(..., description="asyncpg/psycopg DSN: postgresql://user:pass@host:port/db")
    graph_api_version: str = Field("v25.0", description="Meta Graph API version (for the send pass)")

    # ── Runtime tunables (Consul config/reply-service overwrites these) ──
    window_hours: int = 24
    capacity_daily_per_page: int = 1000
    capacity_max_backlog_days: int = 3
    reply_usage_ceiling: float = 60.0
    reply_min_per_hour: int = 30
    reply_max_per_minute: int = 20
    dispatch_tick_seconds: int = 15
    worker_pool_size: int = 12
    send_max_attempts: int = 5
    send_claim_timeout_seconds: int = 120

    @property
    def graph_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.graph_api_version}"

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

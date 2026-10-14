from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List

# JWT secrets that must never be used in production. Any of these (or a secret
# shorter than 32 chars) causes a fail-closed startup error when ENV=production.
_INSECURE_JWT_SECRETS = {
    "",
    "change-me-in-production",
    "changeme-jwt-secret-key-2026",
    "changeme",
    "secret",
    "your-secret-key",
}
_MIN_JWT_SECRET_LENGTH = 32


@dataclass(frozen=True)
class Settings:
    SERVICE_NAME: str = field(default_factory=lambda: os.environ.get("SERVICE_NAME", "dashboard-service"))
    LOG_LEVEL: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    ENV: str = field(default_factory=lambda: os.environ.get("ENV", "production"))
    CORS_ORIGINS: List[str] = field(default_factory=lambda: os.environ.get("CORS_ORIGINS", "http://localhost:4028,http://127.0.0.1:4028").split(","))
    JWT_SECRET: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", "change-me-in-production"))
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24
    DB_HOST: str = field(default_factory=lambda: os.environ.get("DB_HOST", "postgres-db"))
    DB_PORT: str = field(default_factory=lambda: os.environ.get("DB_PORT", "5432"))
    DB_NAME: str = field(default_factory=lambda: (os.environ.get("DB_NAME") or os.environ.get("POSTGRES_DB", "customer_anticipation_db")))
    DB_USER: str = field(default_factory=lambda: (os.environ.get("DB_USER") or os.environ.get("POSTGRES_USER", "scrapper_user")))
    DB_PASSWORD: str = field(default_factory=lambda: (os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD", "")))
    DB_POOL_MIN: int = field(default_factory=lambda: int(os.environ.get("DB_POOL_MIN", "2")))
    DB_POOL_MAX: int = field(default_factory=lambda: int(os.environ.get("DB_POOL_MAX", "10")))
    CONSUL_HOST: str = field(default_factory=lambda: os.environ.get("CONSUL_HOST", "consul"))
    CONSUL_PORT: int = field(default_factory=lambda: int(os.environ.get("CONSUL_PORT", "8500")))

    def __post_init__(self) -> None:
        # Fail closed: refuse to start in production with a weak/default JWT secret.
        # In non-production environments we only warn so local dev stays frictionless.
        is_weak = (
            self.JWT_SECRET in _INSECURE_JWT_SECRETS
            or len(self.JWT_SECRET) < _MIN_JWT_SECRET_LENGTH
        )
        if is_weak:
            msg = (
                "Insecure JWT_SECRET detected. Set a strong, random JWT_SECRET "
                f"(>= {_MIN_JWT_SECRET_LENGTH} chars) via the environment."
            )
            if self.ENV == "production":
                raise RuntimeError(f"{msg} Refusing to start in production.")
            import warnings
            warnings.warn(msg, RuntimeWarning, stacklevel=2)


settings = Settings()

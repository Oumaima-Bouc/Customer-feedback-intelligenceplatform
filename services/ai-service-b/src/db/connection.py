"""
C1 - Infrastructure & Configuration
db/connection.py
Manages the asyncpg connection pool singleton.
All classes call get_pool() - the pool is initialized exactly once.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import asyncpg
import structlog

from config import settings

log = structlog.get_logger(__name__)

_pool: Optional[asyncpg.Pool] = None
_lock = asyncio.Lock()


def _build_dsn() -> str:
    """Construct DSN from DATABASE_URL or individual env vars."""
    dsn = settings.database_url or ""
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    # Validate DSN has user:pass
    if not dsn or ":@" in dsn or "postgresql://@" in dsn:
        user = os.environ.get("POSTGRES_USER") or os.environ.get("DB_USER", "scrapper_user")
        password = os.environ.get("POSTGRES_PASSWORD") or os.environ.get("DB_PASSWORD", "")
        host = os.environ.get("DB_HOST", "postgres-db")
        db = os.environ.get("POSTGRES_DB") or os.environ.get("DB_NAME", "customer_anticipation_db")
        dsn = f"postgresql://{user}:{password}@{host}:5432/{db}"
    return dsn


async def get_pool() -> asyncpg.Pool:
    """
    Returns the shared asyncpg pool. Creates it on first call.
    Thread-safe via asyncio.Lock.
    """
    global _pool
    if _pool is not None:
        return _pool

    async with _lock:
        if _pool is not None:
            return _pool

        dsn = _build_dsn()

        log.info(
            "db.pool.initializing",
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
        )

        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
            command_timeout=30,
            timeout=10,
        )
        log.info("db.pool.ready")
        return _pool


async def close_pool() -> None:
    """Gracefully closes the pool. Call during process shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("db.pool.closed")


async def check_connection() -> bool:
    """Health check: verifies the pool can acquire a connection and run a query."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception as exc:
        log.error("db.health_check.failed", error=str(exc))
        return False

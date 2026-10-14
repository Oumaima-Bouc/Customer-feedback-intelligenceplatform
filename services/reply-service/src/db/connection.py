"""
Synchronous psycopg2 DB access for the enqueue (control-plane) path.

Enqueue runs inside the FastAPI control server's request handlers (a background
thread), so — exactly like ai-service-b's connection_manager — it uses short-lived
synchronous psycopg2 connections (loop-agnostic) rather than an asyncpg pool bound
to one event loop. The dispatcher's asyncpg pool is added in the send-path pass.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from typing import Optional

import psycopg2

from config import settings


def _build_dsn() -> str:
    """Construct a psycopg2 DSN from DATABASE_URL or individual env vars."""
    dsn = (settings.database_url or "").replace("postgresql+asyncpg://", "postgresql://")
    if not dsn or ":@" in dsn or "postgresql://@" in dsn:
        user = os.environ.get("POSTGRES_USER") or os.environ.get("DB_USER", "scrapper_user")
        password = os.environ.get("POSTGRES_PASSWORD") or os.environ.get("DB_PASSWORD", "")
        host = os.environ.get("DB_HOST", "postgres-db")
        db = os.environ.get("POSTGRES_DB") or os.environ.get("DB_NAME", "customer_anticipation_db")
        dsn = f"postgresql://{user}:{password}@{host}:5432/{db}"
    return dsn


@contextmanager
def get_conn():
    """Transactional connection: commits on clean exit, rolls back on error."""
    conn = psycopg2.connect(_build_dsn())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def check_connection() -> bool:
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Async (asyncpg) pool — used by the dispatcher loop on the main event loop.
# Mirrors ai-service-b/db/connection.py. Bound to the loop that first calls
# get_pool(); the enqueue path (control-plane thread) uses the sync helpers above.
# ---------------------------------------------------------------------------
_pool = None
_pool_lock = asyncio.Lock()


def _asyncpg_dsn() -> str:
    return _build_dsn().replace("postgresql+asyncpg://", "postgresql://")


async def get_pool():
    global _pool
    if _pool is not None:
        return _pool
    import asyncpg
    async with _pool_lock:
        if _pool is not None:
            return _pool
        _pool = await asyncpg.create_pool(
            dsn=_asyncpg_dsn(), min_size=2, max_size=10, command_timeout=30, timeout=10
        )
        return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

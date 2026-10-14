"""
Synchronous psycopg2 DB access for the correction (control-plane) path.

The write path runs inside the FastAPI control server's request handlers (a
background thread), so — like reply-service's enqueue path — it uses short-lived
synchronous psycopg2 connections (loop-agnostic) rather than an asyncpg pool.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2

from config import settings


def _build_dsn() -> str:
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

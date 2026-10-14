from __future__ import annotations
from contextlib import contextmanager
import psycopg2.pool
from config.environment import settings
_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(settings.DB_POOL_MIN, settings.DB_POOL_MAX, host=settings.DB_HOST, port=settings.DB_PORT, dbname=settings.DB_NAME, user=settings.DB_USER, password=settings.DB_PASSWORD)
    return _pool
@contextmanager
def get_conn():
    pool = get_pool(); conn = pool.getconn()
    try:
        yield conn; conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        pool.putconn(conn)
def check_connectivity():
    try:
        with get_conn() as conn:
            cur = conn.cursor(); cur.execute("SELECT 1")
        return True
    except Exception:
        return False

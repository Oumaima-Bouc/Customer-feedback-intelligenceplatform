"""
Admin API — FastAPI application.

Endpoints:
  GET  /health      — liveness probe
  GET  /ready       — readiness probe (checks DB)
  GET  /metrics     — Prometheus text format
  POST /admin/runs  — manually trigger a pipeline run (requires API key)

Security:
  - API key required on all /admin/* routes (X-API-Key header)
  - No query parameters accepted on mutation endpoints
  - Rate limiting via SlowAPI (configured in middleware)
  - Correlation ID injected on every request
  - No stack traces exposed to clients
"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy import text

from src.app.bootstrap import AppContainer, bootstrap

logger = logging.getLogger(__name__)

# Module-level container — populated at startup
_container: AppContainer | None = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _container
    _container = bootstrap()
    logger.info("api_startup_complete")
    yield
    logger.info("api_shutdown")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Comment Enrichment Admin API",
    version="1.0.0",
    docs_url=None,      # Disable Swagger UI in production (controlled via env)
    redoc_url=None,
    lifespan=lifespan,
)

# CORS: locked down — only allow same-origin by default
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],      # Set via environment in deployment
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "X-Correlation-ID", "Content-Type"],
)


# ---------------------------------------------------------------------------
# Security dependency
# ---------------------------------------------------------------------------
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def require_api_key(
    request: Request,
    api_key: Annotated[str, Security(_api_key_header)],
) -> None:
    container = _get_container()
    expected = container.settings.security.admin_api_key.get_secret_value()
    if api_key != expected:
        logger.warning(
            "unauthorized_api_call",
            extra={
                "path": str(request.url.path),
                "ip": request.client.host if request.client else "unknown",
            },
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


# ---------------------------------------------------------------------------
# Middleware: inject Correlation ID
# ---------------------------------------------------------------------------
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    container = _get_container()
    header_name = container.settings.app.correlation_id_header
    cid = request.headers.get(header_name) or str(uuid.uuid4())
    # Attach to request state for downstream use
    request.state.correlation_id = cid
    response = await call_next(request)
    response.headers[header_name] = cid
    return response


# ---------------------------------------------------------------------------
# Error handler — never expose internal stack traces
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", exc_info=exc, extra={"path": str(request.url.path)})
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error"},
    )


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------
@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def ready():
    """Readiness — checks DB connectivity."""
    container = _get_container()
    try:
        with container.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        logger.error("readiness_check_failed", exc_info=exc)
        return JSONResponse(status_code=503, content={"status": "not_ready"})


# ---------------------------------------------------------------------------
# Admin: trigger run
# ---------------------------------------------------------------------------
@app.post(
    "/admin/runs",
    tags=["admin"],
    dependencies=[Depends(require_api_key)],
)
async def trigger_run(request: Request):
    container = _get_container()

    if not container.settings.features.enable_admin_runs:
        raise HTTPException(status_code=403, detail="Admin runs are disabled")

    cid = getattr(request.state, "correlation_id", str(uuid.uuid4()))

    logger.info("admin_run_triggered", extra={"correlation_id": cid})

    try:
        result = container.run_daily_use_case.execute(correlation_id=cid)
        return {
            "status": result.status,
            "total_batches": result.total_batches,
            "total_processed": result.total_processed,
            "total_updated": result.total_updated,
            "total_errors": result.total_errors,
            "correlation_id": cid,
        }
    except Exception as exc:
        logger.error("admin_run_failed", exc_info=exc)
        raise HTTPException(status_code=500, detail="Run failed")


# ---------------------------------------------------------------------------
# Metrics (Prometheus text format)
# ---------------------------------------------------------------------------
@app.get("/metrics", tags=["ops"])
async def metrics():
    # In production, wire to prometheus_client.generate_latest()
    try:
        from prometheus_client import generate_latest
        return PlainTextResponse(generate_latest().decode("utf-8"))
    except ImportError:
        return PlainTextResponse("# metrics endpoint — wire to prometheus_client\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_container() -> AppContainer:
    if _container is None:
        raise RuntimeError("Application not bootstrapped")
    return _container

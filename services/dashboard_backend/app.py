from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.environment import settings
from shared.logging_lib.setup import configure_service_logging
from middleware.error_middleware import register_error_handlers
from modules.health.health_controller import router as health_router
from modules.auth.auth_controller import router as auth_router
from modules.dashboard.dashboard_controller import router as dashboard_router
from modules.comments.comments_controller import router as comments_router
from modules.topics.topics_controller import router as topics_router
from modules.settings.settings_controller import router as settings_router
from modules.replies.replies_controller import router as replies_router
from modules.feedback.feedback_controller import router as feedback_router
from modules.system.system_controller import router as system_router

configure_service_logging(
    service_name=settings.SERVICE_NAME,
    log_level=settings.LOG_LEVEL,
    log_format="json",
    log_dir="/logs",
    enable_file_logging=True,
    enable_secret_redaction=True,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Platform Dashboard", description="Configuration management, system monitoring, and data aggregation", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.CORS_ORIGINS if o.strip()], allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], allow_headers=["*"])


@app.middleware("http")
async def request_logging_middleware(request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.exception(
            "http_request_failed",
            extra={
                "event": "http_request_failed",
                "correlation_id": correlation_id,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": duration_ms,
            },
        )
        raise

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Correlation-ID"] = correlation_id
    logger.info(
        "http_request_complete",
        extra={
            "event": "http_request_complete",
            "correlation_id": correlation_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


register_error_handlers(app)
app.include_router(health_router)
app.include_router(auth_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api/dashboard")
app.include_router(comments_router, prefix="/api")
app.include_router(topics_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(replies_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(system_router, prefix="/api")

from __future__ import annotations
import os
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
_IS_DEV = os.environ.get("ENV", "production") == "development"
class AppError(Exception):
    def __init__(self, message: str, status_code: int = 500): super().__init__(message); self.status_code = status_code
class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found"): super().__init__(message, 404)
class ValidationError(AppError):
    def __init__(self, message: str): super().__init__(message, 400)
class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden"): super().__init__(message, 403)
def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError): return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})
    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception): return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": str(exc) if _IS_DEV else "An internal error occurred"})

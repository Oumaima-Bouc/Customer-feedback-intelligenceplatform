"""
shared/meta_graph/errors.py — typed Meta Graph API exceptions.

Extracted verbatim (behaviour-preserving) from ai-service-b so that both the
scraper (ai-service-b) and the reply dispatcher (reply-service) raise and catch
the SAME types. No service-specific imports — this module is dependency-free.
"""
from __future__ import annotations


# ── Non-retryable graph errors ────────────────────────────────────────────────
class GraphClientError(Exception):
    """Base for all non-retryable graph client errors."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Meta API error {code}: {message}")


class TokenExpiredError(GraphClientError):
    """Access token is invalid/expired — requires manual intervention."""


class PostNotFoundError(GraphClientError):
    """Post/object was deleted or is inaccessible."""


class PermissionError(GraphClientError):  # noqa: A001 — intentional shadow, preserved from original
    """App/token lacks permission for this resource."""


# ── Rate / quota signals ──────────────────────────────────────────────────────
class APIQuotaWarning(Exception):
    """Raised when X-App-Usage exceeds the configured soft threshold."""

    def __init__(self, quota_pct: float, threshold: float):
        self.quota_pct = quota_pct
        self.threshold = threshold
        super().__init__(
            f"API quota at {quota_pct:.1%} - threshold {threshold:.1%} exceeded"
        )


class APIRateLimitException(Exception):
    """Raised when Meta returns HTTP 429 (hard rate limit)."""

    def __init__(self, status: int = 429):
        self.status = status
        super().__init__(f"Meta API returned HTTP {status} - hard rate limit")


class CursorExpiredException(Exception):
    """Raised when Meta returns an invalid/expired pagination cursor error."""

    def __init__(self, error_code: int, message: str = ""):
        self.error_code = error_code
        super().__init__(f"Cursor expired (Meta error {error_code}): {message}")


class _RetryableError(Exception):
    """Internal sentinel for errors that should trigger a retry."""

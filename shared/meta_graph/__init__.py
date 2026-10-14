"""
shared/meta_graph — Meta Graph API client + rate guard + typed errors.

Shared by ai-service-b (scraper) and reply-service (Group Reply dispatcher) so
both raise/catch identical types and share one resilience implementation.
"""
from shared.meta_graph.errors import (
    APIQuotaWarning,
    APIRateLimitException,
    CursorExpiredException,
    GraphClientError,
    PermissionError,  # noqa: A004
    PostNotFoundError,
    TokenExpiredError,
)
from shared.meta_graph.graph_client import (
    GraphClient,
    check_write_permission,
    compute_can_reply,
    derive_permissions,
)
from shared.meta_graph.rate_guard import RateGuard

__all__ = [
    "GraphClient",
    "RateGuard",
    "check_write_permission",
    "compute_can_reply",
    "derive_permissions",
    "GraphClientError",
    "TokenExpiredError",
    "PostNotFoundError",
    "PermissionError",
    "APIQuotaWarning",
    "APIRateLimitException",
    "CursorExpiredException",
]

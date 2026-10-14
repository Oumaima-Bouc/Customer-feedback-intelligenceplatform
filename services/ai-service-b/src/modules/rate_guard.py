"""
Compatibility shim — the implementation moved to `shared/meta_graph`.

Kept so existing imports (`from modules.rate_guard import RateGuard, ...`)
continue to work unchanged. New code should import from `shared.meta_graph`.
"""
from shared.meta_graph.rate_guard import RateGuard  # noqa: F401
from shared.meta_graph.errors import (  # noqa: F401
    APIQuotaWarning,
    APIRateLimitException,
    CursorExpiredException,
)

"""
Compatibility shim — the implementation moved to `shared/meta_graph`.

Kept so existing imports (`from api.graph_client import GraphClient, ...`) across
the scraper continue to work unchanged. New code should import from
`shared.meta_graph` directly.
"""
from shared.meta_graph.graph_client import (  # noqa: F401
    FATAL_ERROR_CODES,
    RETRYABLE_STATUS,
    GraphClient,
)
from shared.meta_graph.errors import (  # noqa: F401
    GraphClientError,
    PermissionError,  # noqa: A004
    PostNotFoundError,
    TokenExpiredError,
)

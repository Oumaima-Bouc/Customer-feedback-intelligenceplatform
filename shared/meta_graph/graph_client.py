"""
shared/meta_graph/graph_client.py — resilient Meta Graph API client.

Extracted from ai-service-b/api/graph_client.py. Behaviour of the GET/retry path
is preserved exactly; the only change is that `base_url`, `access_token`, and
`max_attempts` are now CONSTRUCTOR-INJECTED (the original read them from a service
`settings` singleton), making the client shared between the scraper and the reply
dispatcher.

New (reply) capabilities:
  - post_reply(comment_id, message)        — the Group Reply write
  - check_write_permission(base_url, token, page_id) — onboarding probe
  - compute_can_reply(tasks)               — pure task→capability mapping
"""
from __future__ import annotations

import asyncio
import random
from typing import Any, Optional

import aiohttp
import structlog

from shared.meta_graph.errors import (
    APIQuotaWarning,
    APIRateLimitException,
    CursorExpiredException,
    GraphClientError,
    PermissionError,  # noqa: A004 — preserved name
    PostNotFoundError,
    TokenExpiredError,
    _RetryableError,
)
from shared.meta_graph.rate_guard import RateGuard

log = structlog.get_logger(__name__)

# Non-retryable Meta error codes
FATAL_ERROR_CODES = {190, 200, 10, 803, 368}
# Retryable HTTP status codes
RETRYABLE_STATUS = {500, 502, 503, 504}

# Page-token "tasks" that imply the ability to reply to / moderate comments.
# NOTE: the exact task→capability mapping and the required write scope
# (pages_manage_engagement) MUST be verified against the pinned GRAPH_API_VERSION
# during live integration. This mapping is the documented best-effort default.
_REPLY_TASKS = {"MODERATE", "CREATE_CONTENT", "MANAGE"}


def compute_can_reply(tasks: Optional[list]) -> bool:
    """Pure mapping: does this page-token task list permit replying to comments?"""
    if not tasks:
        return False
    return any(t in _REPLY_TASKS for t in tasks)


# Graph scopes that grant each capability (read from debug_token).
_SCRAPE_SCOPES = frozenset({"pages_read_engagement", "pages_read_user_content"})
_REPLY_SCOPES = frozenset({"pages_manage_engagement"})

# Operator-facing guidance shown when a permission is missing.
SCRAPE_MISSING_REASON = (
    "Comment-read permission missing — grant pages_read_engagement to this token."
)
REPLY_MISSING_REASON = (
    "Replies disabled — grant pages_manage_engagement to enable replies."
)


def derive_permissions(
    scopes: Optional[list], feed_ok: Optional[bool] = None
) -> tuple[bool, bool, Optional[str], Optional[str]]:
    """
    Pure mapping from a token's granted **scopes** (from debug_token) to the two
    capabilities the platform cares about, plus operator-facing reasons.

    - Page tokens don't expose `tasks` on the page node; the reliable signal is the
      token's granted scopes: pages_read_engagement (scrape) and
      pages_manage_engagement (reply).
    - If scopes couldn't be read (debug_token unavailable), fall back to a behavioral
      `feed_ok` probe for scrape; reply is treated as unverified (False, locked).

    Returns (can_scrape, can_reply, scrape_reason, reply_reason).
    """
    if scopes is not None:
        s = set(scopes)
        can_scrape = bool(s & _SCRAPE_SCOPES)
        can_reply = bool(s & _REPLY_SCOPES)
    else:
        can_scrape = bool(feed_ok)
        can_reply = False
    scrape_reason = None if can_scrape else SCRAPE_MISSING_REASON
    reply_reason = None if can_reply else REPLY_MISSING_REASON
    return can_scrape, can_reply, scrape_reason, reply_reason


class GraphClient:
    """
    Async HTTP client for the Meta Graph API.

    Parameters
    ----------
    base_url:      e.g. "https://graph.facebook.com/v25.0"
    access_token:  the page/user token (REQUIRED — no global fallback in shared code)
    rate_guard:    post-response rate middleware (REQUIRED)
    max_attempts:  retry ceiling for transient errors
    recovery:      optional; stored for callers that pass it (unused by the client itself)
    """

    def __init__(
        self,
        *,
        base_url: str,
        access_token: str,
        rate_guard: RateGuard,
        max_attempts: int = 3,
        recovery: Any = None,
    ) -> None:
        self._base_url = base_url
        self._token = access_token
        self._guard = rate_guard
        self._max_attempts = max_attempts
        self._recovery = recovery
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "GraphClient":
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30, connect=10),
            headers={"Accept": "application/json"},
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    # ── GET (unchanged behaviour) ─────────────────────────────────────────────
    async def get(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        full_params = {**(params or {}), "access_token": self._token}
        return await self._get_with_retry(url, full_params)

    async def _get_with_retry(self, url: str, params: dict[str, Any], attempt: int = 0) -> dict[str, Any]:
        assert self._session is not None, "GraphClient must be used as async context manager"
        try:
            async with self._session.get(url, params=params) as resp:
                await self._guard.check(resp)
                if resp.status in RETRYABLE_STATUS:
                    raise _RetryableError(f"HTTP {resp.status}")
                data: dict[str, Any] = await resp.json()
            self._raise_for_meta_error(data)
            return data
        except (APIQuotaWarning, APIRateLimitException, CursorExpiredException):
            raise
        except _RetryableError as exc:
            return await self._handle_retry(url, params, attempt, str(exc))
        except aiohttp.ClientError as exc:
            return await self._handle_retry(url, params, attempt, str(exc))

    async def _handle_retry(self, url: str, params: dict[str, Any], attempt: int, reason: str) -> dict[str, Any]:
        if attempt >= self._max_attempts - 1:
            log.error("graph_client.max_retries_exceeded", url=url, attempts=attempt + 1, reason=reason)
            raise GraphClientError(code=0, message=f"Max retries exceeded: {reason}")
        delay = (2 ** (attempt + 1)) * (1 + random.uniform(-0.2, 0.2))
        log.warning("graph_client.retry", attempt=attempt + 1, max_attempts=self._max_attempts, delay_s=round(delay, 2), reason=reason)
        await asyncio.sleep(delay)
        return await self._get_with_retry(url, params, attempt + 1)

    # ── POST / reply (new) ────────────────────────────────────────────────────
    async def post_reply(self, comment_id: str, message: str) -> str:
        """
        Publish a reply under a comment and return the created reply's id.

        Meta edge: POST /{comment_id}/comments  body: message=<text>
        (Verify the edge + the pages_manage_engagement scope against the pinned
        GRAPH_API_VERSION during live integration.)

        Idempotency-aware ordering: a 429 means Meta REJECTED the request (nothing
        created) -> raise APIRateLimitException so the caller backs off and retries.
        Once a reply IS created we capture its id and only THEN `observe()` the
        usage headers (never raise after a successful write) so the caller can stop
        on quota without unwinding a send. 5xx/network retry the same as GET.
        """
        assert self._session is not None, "GraphClient must be used as async context manager"
        url = f"{self._base_url}/{comment_id}/comments"
        data = {"message": message, "access_token": self._token}

        for attempt in range(self._max_attempts):
            try:
                async with self._session.post(url, data=data) as resp:
                    if resp.status == 429:
                        raise APIRateLimitException(status=429)  # rejected — safe to retry
                    if resp.status in RETRYABLE_STATUS:
                        raise _RetryableError(f"HTTP {resp.status}")
                    body: dict[str, Any] = await resp.json()
                    # Reply (if any) is created at this point — update usage, never raise here.
                    self._guard.observe(resp)
                # Raises token/permission/not-found/fatal — all mean NOT created.
                self._raise_for_meta_error(body)
                reply_id = body.get("id")
                if not reply_id:
                    raise GraphClientError(code=0, message="Reply response had no id")
                return str(reply_id)
            except APIRateLimitException:
                raise
            except _RetryableError as exc:
                if attempt >= self._max_attempts - 1:
                    raise GraphClientError(code=0, message=f"Max retries exceeded: {exc}")
                delay = (2 ** (attempt + 1)) * (1 + random.uniform(-0.2, 0.2))
                log.warning("graph_client.reply_retry", attempt=attempt + 1, delay_s=round(delay, 2), reason=str(exc))
                await asyncio.sleep(delay)
            except aiohttp.ClientError as exc:
                if attempt >= self._max_attempts - 1:
                    raise GraphClientError(code=0, message=f"Max retries exceeded: {exc}")
                await asyncio.sleep((2 ** (attempt + 1)) * (1 + random.uniform(-0.2, 0.2)))
        raise GraphClientError(code=0, message="post_reply exhausted retries")

    # ── Meta error mapping (unchanged) ────────────────────────────────────────
    @staticmethod
    def _raise_for_meta_error(data: dict[str, Any]) -> None:
        error = data.get("error")
        if not error:
            return
        code: int = error.get("code", 0)
        message: str = error.get("message", "")
        fbtrace: str = error.get("fbtrace_id", "")
        log.error("graph_client.meta_error", code=code, message=message, fbtrace_id=fbtrace)
        if code == 190:
            raise TokenExpiredError(code=code, message=message)
        if code == 803:
            raise PostNotFoundError(code=code, message=message)
        if code in (200, 10):
            raise PermissionError(code=code, message=message)
        RateGuard.check_cursor_error(code, message)
        if code in FATAL_ERROR_CODES:
            raise GraphClientError(code=code, message=message)
        raise _RetryableError(f"Meta error {code}: {message}")


async def check_write_permission(base_url: str, token: str, page_id: str) -> dict[str, Any]:
    """
    Side-effect-free onboarding probe: does this token grant reply capability
    for the page?  Reads the page node's `tasks` and maps them via compute_can_reply.

    Returns {"can_reply": bool, "reason": str|None}.
    """
    url = f"{base_url}/{page_id}"
    params = {"fields": "id,name,tasks", "access_token": token}
    try:
        timeout = aiohttp.ClientTimeout(total=20, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        return {"can_reply": False, "reason": f"Could not reach Meta Graph API ({exc})."}

    if not isinstance(data, dict):
        return {"can_reply": False, "reason": "Unexpected response from Meta Graph API."}
    error = data.get("error")
    if error:
        return {"can_reply": False, "reason": error.get("message", "Permission probe failed.")}

    tasks = data.get("tasks")
    if compute_can_reply(tasks):
        return {"can_reply": True, "reason": None}
    return {
        "can_reply": False,
        "reason": "This page hasn't granted reply (engagement) permission to this token.",
    }

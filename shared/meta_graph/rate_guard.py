"""
shared/meta_graph/rate_guard.py — post-response rate middleware.

Extracted from ai-service-b/modules/rate_guard.py. The only behavioural change
is that thresholds are now CONSTRUCTOR-INJECTED instead of read from a service
`settings` singleton, so the module is service-agnostic (shared by the scraper
and the reply dispatcher). Defaults preserve the original scraper behaviour.
"""
from __future__ import annotations

import json
from typing import Optional

import structlog

from shared.meta_graph.errors import (
    APIQuotaWarning,
    APIRateLimitException,
    CursorExpiredException,
)

log = structlog.get_logger(__name__)


class RateGuard:
    """
    Stateful rate guard. One instance per pipeline/dispatch run, shared for the
    lifetime of a single Graph client.

    Parameters
    ----------
    rate_limit_threshold:
        Quota fraction (0..1) above which `check()` raises APIQuotaWarning.
    like_skip_threshold:
        Quota fraction above which non-essential calls (e.g. like-sync) should
        be skipped (`should_skip_like_sync`).
    """

    def __init__(
        self,
        rate_limit_threshold: float = 0.85,
        like_skip_threshold: float = 0.90,
    ) -> None:
        self._rate_limit_threshold = rate_limit_threshold
        self._like_skip_threshold = like_skip_threshold
        self._quota_pct: float = 0.0
        self._call_count: int = 0

    @property
    def quota_pct(self) -> float:
        """Most recent usage percentage (0.0-1.0)."""
        return self._quota_pct

    @property
    def should_skip_like_sync(self) -> bool:
        """True when quota is above the like-sync skip threshold."""
        return self._quota_pct > self._like_skip_threshold

    async def check(self, response) -> None:
        """
        Post-response hook. Call after EVERY Meta API response.

        Raises:
            APIRateLimitException: on HTTP 429.
            APIQuotaWarning: when X-App-Usage exceeds rate_limit_threshold.
        """
        self._call_count += 1

        if response.status == 429:
            log.error("rate_guard.hard_limit", status=response.status, quota_pct=self._quota_pct)
            raise APIRateLimitException(status=response.status)

        usage_pct = self._parse_usage_header(response)
        if usage_pct is not None:
            self._quota_pct = usage_pct

        if self._quota_pct > self._rate_limit_threshold:
            log.warning(
                "rate_guard.quota_warning",
                quota_pct=f"{self._quota_pct:.1%}",
                threshold=f"{self._rate_limit_threshold:.1%}",
                calls_made=self._call_count,
            )
            raise APIQuotaWarning(quota_pct=self._quota_pct, threshold=self._rate_limit_threshold)

        log.debug("rate_guard.ok", quota_pct=f"{self._quota_pct:.1%}", status=response.status)

    def observe(self, response) -> None:
        """
        Update quota_pct from response headers WITHOUT raising.

        Used by non-idempotent writes (post_reply): the write has already
        happened, so the caller must inspect quota_pct afterwards rather than
        have an exception unwind a successful send.
        """
        usage_pct = self._parse_usage_header(response)
        if usage_pct is not None:
            self._quota_pct = usage_pct

    def _parse_usage_header(self, response) -> Optional[float]:
        """
        Parse X-App-Usage / X-Business-Use-Case-Usage headers.
        Returns the highest usage percentage found (0.0-1.0), or None.
        """
        for header_name in ("X-App-Usage", "X-Business-Use-Case-Usage"):
            raw = response.headers.get(header_name)
            if not raw:
                continue
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    values = [v for v in data.values() if isinstance(v, (int, float))]
                    if values:
                        return max(values) / 100.0
                elif isinstance(data, list):
                    all_vals: list[float] = []
                    for item in data:
                        if isinstance(item, dict):
                            all_vals.extend(
                                v / 100.0 for v in item.values() if isinstance(v, (int, float))
                            )
                    if all_vals:
                        return max(all_vals)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                log.warning("rate_guard.header_parse_error", header=header_name, error=str(exc))
        return None

    @staticmethod
    def check_cursor_error(error_code: int, message: str = "") -> None:
        """Raise CursorExpiredException for known cursor-related Meta error codes."""
        cursor_error_codes = {1, 2, 100, 190}
        if error_code in cursor_error_codes and "cursor" in message.lower():
            raise CursorExpiredException(error_code=error_code, message=message)

"""
C5 - Resilience & Recovery
modules/recovery.py
Orchestrates the pause-persist-hibernate-resume cycle.
Called by C3's graph_client when APIQuotaWarning or APIRateLimitException fires.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable, Awaitable, Optional

import structlog

from config import settings

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)

JOB_ID = "meta_page_scraper"


# -- Backoff formula --
# Decision SC-3: min(15 * 2^n, 240) minutes

def compute_backoff_minutes(attempt: int) -> int:
    return min(15 * (2 ** attempt), 240)


def compute_resume_at(attempt: int) -> datetime:
    minutes = compute_backoff_minutes(attempt)
    return datetime.now(tz=timezone.utc) + timedelta(minutes=minutes)


# -- Recovery Manager --

class RecoveryManager:
    """
    Stateless orchestrator for rate-limit recovery.
    C3 creates one instance per pipeline run and passes it into graph_client.
    """

    def __init__(
        self,
        signal_pause_fn: Callable[[str, str, int], Awaitable[None]],
    ) -> None:
        self._signal_pause = signal_pause_fn

    async def handle_rate_limit(
        self,
        post_id: str,
        cursor: str,
        current_attempt: int,
    ) -> None:
        """
        Full pause sequence on rate limit detection.
        """
        next_attempt = current_attempt + 1
        backoff_m = compute_backoff_minutes(current_attempt)
        resume_at = compute_resume_at(current_attempt)

        log.warning(
            "recovery.rate_limit.pausing",
            post_id=post_id,
            cursor=cursor[:20] + "..." if len(cursor) > 20 else cursor,
            attempt=current_attempt,
            next_attempt=next_attempt,
            backoff_minutes=backoff_m,
            resume_at=resume_at.isoformat(),
        )

        try:
            await self._signal_pause(post_id, cursor, next_attempt)
            log.info(
                "recovery.pause.persisted",
                resume_at=resume_at.isoformat(),
                backoff_minutes=backoff_m,
            )
        except Exception as exc:
            log.error(
                "recovery.pause.persist_failed",
                error=str(exc),
                post_id=post_id,
            )
            raise

    async def handle_cursor_expiry(
        self,
        post_id: str,
        last_success_at: Optional[datetime],
    ) -> Optional[datetime]:
        """
        Called by C3's comment engine when CursorExpiredException is caught.
        Returns the fallback timestamp for timestamp-based pagination restart.
        """
        log.warning(
            "recovery.cursor_expired",
            post_id=post_id,
            fallback_timestamp=last_success_at.isoformat() if last_success_at else "none",
        )
        return last_success_at

"""
Page selection & scrape/reply coordination (R5, R6).

`decide_page` is a pure function (no DB) so the coordination policy is fully
unit-testable. A page is eligible to send *now* only when the scraper isn't
actively using its token and usage has headroom; otherwise a guaranteed drip
(reply_min_per_hour) keeps reply from being starved.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog

from db.queries import QD

log = structlog.get_logger(__name__)


def slice_size(reply_max_per_minute: int, tick_seconds: int) -> int:
    """Max sends per page per tick from the per-minute pace."""
    return max(1, (int(reply_max_per_minute) * int(tick_seconds)) // 60)


def drip_interval_seconds(reply_min_per_hour: int) -> float:
    """Seconds between guaranteed drip sends; 0 disables the drip floor."""
    if reply_min_per_hour <= 0:
        return 0.0
    return 3600.0 / float(reply_min_per_hour)


def decide_page(
    *,
    now: datetime,
    scraper_status: str,
    resume_at: Optional[datetime],
    app_usage_pct: float,
    last_sent: Optional[datetime],
    ceiling: float,
    drip_interval_s: float,
    slice_n: int,
) -> tuple[Optional[str], int]:
    """
    Return (mode, max_sends):
      ("normal", slice_n) — scraper idle & usage has headroom → full paced slice
      ("drip", 1)         — gated, but the anti-starvation floor is due → one send
      (None, 0)           — gated and drip not due → skip this tick

    `app_usage_pct` and `ceiling` are both percentages (0-100).
    """
    gated = (
        scraper_status == "RUNNING"                       # scraper is foreground on this token
        or (resume_at is not None and resume_at > now)    # scraper in quota backoff
        or (float(app_usage_pct) >= float(ceiling))       # below the scraper's pause point, but no headroom
    )
    if not gated:
        return "normal", slice_n
    if drip_interval_s > 0 and (last_sent is None or (now - last_sent).total_seconds() >= drip_interval_s):
        return "drip", 1
    return None, 0


async def select_due_pages(pool, settings) -> list[dict]:
    """Query pages with due work and apply the coordination policy per page."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(QD.SELECT_DUE_PAGES)

    now = datetime.now(timezone.utc)
    sl = slice_size(settings.reply_max_per_minute, settings.dispatch_tick_seconds)
    drip = drip_interval_seconds(settings.reply_min_per_hour)

    pages: list[dict] = []
    for r in rows:
        mode, max_sends = decide_page(
            now=now,
            scraper_status=r["scraper_status"],
            resume_at=r["resume_at"],
            app_usage_pct=r["app_usage_pct"],
            last_sent=r["last_sent"],
            ceiling=settings.reply_usage_ceiling,
            drip_interval_s=drip,
            slice_n=sl,
        )
        if mode is None:
            continue
        pages.append(
            {
                "source_id": r["source_id"],
                "access_token": r["access_token"],
                "platform": r["platform"],
                "mode": mode,
                "max_sends": max_sends,
            }
        )
    if pages:
        log.info("reply.pages_selected", count=len(pages))
    return pages

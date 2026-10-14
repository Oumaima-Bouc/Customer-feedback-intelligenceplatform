"""
Per-page 24h-window capacity assignment with spill / carry-over (R1, R7).

Pure function — no DB, no I/O — so it is exhaustively unit-testable. Given a
page's existing per-day load, it assigns each new job a `scheduled_for`:
fill today's remaining capacity, then spill to D+1, D+2, ... New submissions are
naturally appended after whatever a future day already holds (the caller passes
the live per-day counts).

The window is modeled as a UTC calendar day for the MVP. `window_hours` is carried
for the ETA computation and future sub-day windowing; it does not change the
day-bucketing here.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def window_start(d: date) -> datetime:
    """UTC start-of-day for a window date."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def assign_schedule(
    now: datetime,
    per_day_existing: dict[date, int],
    capacity: int,
    count: int,
    max_backlog_days: int = 3,  # noqa: ARG001 — affects ETA/back-pressure messaging, not bucketing
    window_hours: int = 24,     # noqa: ARG001 — reserved for sub-day windows
) -> tuple[list[datetime], date]:
    """
    Returns (scheduled_for per job — length == count, furthest_date).

    Jobs assigned to *today* get `now` (sendable on the next dispatch tick);
    jobs assigned to a future day D get window_start(D).
    """
    capacity = max(int(capacity), 1)  # schema enforces >= 1; defensive against div/loop traps
    now = now.astimezone(timezone.utc)
    today = now.date()
    existing = dict(per_day_existing or {})

    assignments: list[datetime] = []
    remaining = int(count)
    day = today
    while remaining > 0:
        used = existing.get(day, 0)
        free = max(capacity - used, 0)
        take = min(free, remaining)
        for _ in range(take):
            assignments.append(now if day == today else window_start(day))
        existing[day] = used + take
        remaining -= take
        if remaining > 0:
            day = day + timedelta(days=1)

    furthest = assignments[-1].astimezone(timezone.utc).date() if assignments else today
    return assignments, furthest

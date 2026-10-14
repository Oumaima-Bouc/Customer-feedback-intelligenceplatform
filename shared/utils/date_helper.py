from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, List, Optional
def to_iso(value: Optional[Any]) -> Optional[str]:
    if value is None: return None
    if isinstance(value, datetime): return value.isoformat()
    return str(value)
def compute_next_cron_runs(cron: str, count: int = 3) -> List[str]:
    try:
        from apscheduler.triggers.cron import CronTrigger
        trigger = CronTrigger.from_crontab(cron)
        now = datetime.now(timezone.utc)
        times: List[str] = []
        for _ in range(count):
            next_run = trigger.get_next_fire_time(None, now)
            if next_run: times.append(next_run.isoformat()); now = next_run
        return times
    except Exception:
        return []
def utc_now_iso() -> str: return datetime.now(timezone.utc).isoformat()

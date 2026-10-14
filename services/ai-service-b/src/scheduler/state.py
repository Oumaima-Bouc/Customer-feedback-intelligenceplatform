"""
Scheduler state — process-global references to the running AsyncIOScheduler and
the event loop that owns it.

The FastAPI control endpoints run in a separate (health-server) thread. Because
AsyncIOScheduler.add_job()/remove_job() call loop.call_later() (which is NOT
thread-safe), schedule mutations must be marshaled back onto the scheduler's own
loop via asyncio.run_coroutine_threadsafe(). The loop reference stored here is
what makes that possible.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

_scheduler: Optional[AsyncIOScheduler] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def set_active_scheduler(scheduler: AsyncIOScheduler, loop: asyncio.AbstractEventLoop) -> None:
    global _scheduler, _loop
    _scheduler = scheduler
    _loop = loop


def get_active_scheduler() -> Optional[AsyncIOScheduler]:
    return _scheduler


def get_scheduler_loop() -> Optional[asyncio.AbstractEventLoop]:
    return _loop

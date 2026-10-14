"""
Zombie-claim reclaimer (reuses ai-service-b's stale-worker idea, R9/R10).

If a worker crashes after claiming jobs ('sending') but before recording an
outcome, those jobs would otherwise stay stuck. Each dispatcher tick resets
'sending' jobs whose claim is older than send.claim_timeout_seconds back to
'pending' so another worker re-attempts them. Safe because a genuinely-sent job
is already 'sent' (not 'sending').
"""
from __future__ import annotations

import structlog

from db.queries import QD

log = structlog.get_logger(__name__)


async def reclaim_stale(pool, claim_timeout_seconds: int) -> None:
    async with pool.acquire() as conn:
        result = await conn.execute(QD.RECLAIM_STALE, int(claim_timeout_seconds))
    # asyncpg returns e.g. "UPDATE 3"
    if isinstance(result, str) and result.startswith("UPDATE") and result != "UPDATE 0":
        log.warning("reply.reclaimed_stale", detail=result)

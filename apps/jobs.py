"""Small Redis job producer shared by API adapters.

Payloads are deliberately JSON-only and never logged.  A stable job id makes
dead-letter investigation possible without exposing email tokens or content.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from engine.core.config import Settings
from engine.core.ids import new_id
from engine.core.logging import get_logger

logger = get_logger("jobs")
QUEUE = "narrative:jobs"
DEAD_LETTER_QUEUE = "narrative:jobs:dead"


async def enqueue_job(
    settings: Settings,
    job_type: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Queue a job when Redis is configured; return False for safe inline fallback."""
    if not settings.redis_url:
        return False
    from redis.asyncio import from_url

    redis = from_url(settings.redis_url, decode_responses=True)
    envelope = {
        "id": new_id(),
        "type": job_type,
        "attempt": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "payload": payload or {},
    }
    try:
        await redis.rpush(QUEUE, json.dumps(envelope, ensure_ascii=False))
        return True
    except Exception:
        logger.exception("background job enqueue failed: type=%s id=%s", job_type, envelope["id"])
        return False
    finally:
        await redis.aclose()

from __future__ import annotations

import pytest

from apps.worker.main import poll_job


class IdleRedis:
    async def blpop(self, _queue: str, *, timeout: int):
        from redis.exceptions import TimeoutError as RedisTimeoutError

        assert timeout == 30
        raise RedisTimeoutError("idle blocking pop")


@pytest.mark.asyncio
async def test_idle_redis_timeout_is_treated_as_empty_queue() -> None:
    assert await poll_job(IdleRedis()) is None

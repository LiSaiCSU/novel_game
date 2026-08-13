"""Distributed fixed-window rate limits with a local-development fallback."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._redis: dict[str, object] = {}

    async def check(
        self,
        key: str,
        limit: int,
        seconds: int,
        *,
        redis_url: str = "",
    ) -> None:
        if redis_url:
            await self._check_redis(redis_url, key, limit, seconds)
            return
        now = asyncio.get_running_loop().time()
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= now - seconds:
                events.popleft()
            if len(events) >= limit:
                raise HTTPException(status_code=429, detail="too many requests")
            events.append(now)

    async def _check_redis(
        self, redis_url: str, key: str, limit: int, seconds: int
    ) -> None:
        client = self._redis.get(redis_url)
        if client is None:
            from redis.asyncio import from_url

            client = from_url(redis_url, decode_responses=True)
            self._redis[redis_url] = client
        script = (
            "local count = redis.call('INCR', KEYS[1]); "
            "if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]); end; "
            "return count"
        )
        try:
            count = int(
                await client.eval(  # type: ignore[attr-defined]
                    script, 1, f"narrative:rate:{key}", seconds
                )
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="rate limit service unavailable") from exc
        if count > limit:
            raise HTTPException(status_code=429, detail="too many requests")

    async def close(self) -> None:
        for client in self._redis.values():
            await client.aclose()  # type: ignore[attr-defined]
        self._redis.clear()
        self._events.clear()


rate_limiter = RateLimiter()

"""World locking and idempotency (Prompt section 59).

Correctness of the world state comes from the database transaction. These
primitives only stop the *same* work from running twice concurrently
(DECISIONS D-003).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol, runtime_checkable

from engine.core.errors import ConcurrencyError


@runtime_checkable
class LockBackend(Protocol):
    @asynccontextmanager
    def acquire(self, key: str, ttl_seconds: float = 120.0) -> AsyncIterator[None]: ...


@runtime_checkable
class IdempotencyStore(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...
    async def put(self, key: str, value: dict[str, Any], ttl_seconds: float = 3600.0) -> None: ...


class InMemoryLockBackend:
    """Process-local lock. Correct for single-process deployments."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._timeout = timeout_seconds

    @asynccontextmanager
    async def acquire(self, key: str, ttl_seconds: float = 120.0) -> AsyncIterator[None]:
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            await asyncio.wait_for(lock.acquire(), timeout=self._timeout)
        except TimeoutError as exc:
            raise ConcurrencyError(f"could not acquire lock {key}", key=key) from exc
        try:
            yield
        finally:
            lock.release()


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, dict[str, Any]]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            self._data.pop(key, None)
            return None
        return value

    async def put(self, key: str, value: dict[str, Any], ttl_seconds: float = 3600.0) -> None:
        self._data[key] = (time.time() + ttl_seconds, value)

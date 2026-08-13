from __future__ import annotations

import asyncio

from engine.core.locks import InMemoryLockBackend


async def test_same_world_lock_serializes_fifty_concurrent_entries() -> None:
    backend = InMemoryLockBackend(timeout_seconds=5)
    active = 0
    maximum_active = 0
    completed: list[int] = []

    async def enter(index: int) -> None:
        nonlocal active, maximum_active
        async with backend.acquire("world:shared"):
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0)
            completed.append(index)
            active -= 1

    await asyncio.gather(*(enter(index) for index in range(50)))

    assert maximum_active == 1
    assert len(completed) == 50


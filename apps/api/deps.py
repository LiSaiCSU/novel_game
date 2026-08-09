"""FastAPI dependencies: settings, content pack, orchestrator, unit of work."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends

from database.repositories.sql import SqlUnitOfWork
from database.session import get_sessionmaker
from engine.contentpack.pack import ContentPack, load_content_pack
from engine.core.config import Settings, get_settings
from engine.orchestrator.factory import build_orchestrator
from engine.orchestrator.orchestrator import GameOrchestrator


def settings_dep() -> Settings:
    return get_settings()


@lru_cache(maxsize=4)
def _load_pack(content_dir: str, pack_key: str) -> ContentPack:
    return load_content_pack(content_dir, pack_key)


def pack_dep(settings: Settings = Depends(settings_dep)) -> ContentPack:
    return _load_pack(str(settings.content_path), settings.content_pack)


@lru_cache(maxsize=1)
def _orchestrator() -> GameOrchestrator:
    return build_orchestrator()


def orchestrator_dep() -> GameOrchestrator:
    return _orchestrator()


async def uow_dep() -> AsyncIterator[SqlUnitOfWork]:
    """One database session, and therefore one transaction, per request."""
    maker = get_sessionmaker()
    async with maker() as session:
        uow = SqlUnitOfWork(session)
        try:
            yield uow
        except Exception:
            await uow.rollback()
            raise

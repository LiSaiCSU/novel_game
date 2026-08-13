"""Async engine and session factory."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from database.base import Base
from database.models import orm as _orm  # noqa: F401
from database.models import platform as _platform  # noqa: F401
from engine.core.config import Settings, get_settings
from engine.core.logging import get_logger

logger = get_logger("database")

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def prepare_database_path(url: str) -> None:
    """Create the parent directory required by a file-backed SQLite URL."""
    if not url.startswith("sqlite"):
        return
    _, _, path = url.partition("///")
    if not path or path == ":memory:":
        return
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    settings = settings or get_settings()
    prepare_database_path(settings.database_url)
    engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        future=True,
        pool_pre_ping=not settings.database_url.startswith("sqlite"),
    )
    threshold = settings.slow_query_seconds

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        del cursor, statement, parameters, context, executemany
        conn.info.setdefault("query_started_at", []).append(time.perf_counter())

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        del cursor, parameters, context, executemany
        started = conn.info.get("query_started_at", []).pop()
        elapsed = time.perf_counter() - started
        if elapsed >= threshold:
            operation = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else "UNKNOWN"
            fingerprint = hashlib.sha256(statement.encode("utf-8")).hexdigest()[:16]
            logger.warning(
                "slow query duration_ms=%.1f operation=%s fingerprint=%s",
                elapsed * 1000,
                operation,
                fingerprint,
            )

    return engine


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings)
    return _engine


def get_sessionmaker(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(settings), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


async def create_all(engine: AsyncEngine | None = None) -> None:
    """Dev/test convenience. Production schema changes go through Alembic."""
    target = engine or get_engine()
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all(engine: AsyncEngine | None = None) -> None:
    target = engine or get_engine()
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None

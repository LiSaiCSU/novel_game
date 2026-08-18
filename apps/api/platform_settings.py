"""Deployment-wide switches an administrator can change without a deploy.

Read paths run on every page load, so they are written to be cheap and to
never fail loudly: a missing row, an unreadable value or a table that has not
been migrated yet all return the documented default rather than breaking the
request that asked.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from database.models.platform import PlatformSettingORM
from database.repositories.sql import SqlUnitOfWork
from engine.core.logging import get_logger

logger = get_logger("platform-settings")

DEFAULT_QUOTA_KEY = "default_quota"
ANNOUNCEMENT_KEY = "announcement"

DEFAULT_QUOTA_FALLBACK: dict[str, Any] = {"monthly_tokens": 200_000}
EMPTY_ANNOUNCEMENT: dict[str, Any] = {"message": "", "level": "info", "active": False}


async def read_setting(uow: SqlUnitOfWork, key: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        row = await uow.session.scalar(
            sa.select(PlatformSettingORM).where(PlatformSettingORM.key == key)
        )
    except Exception:
        # A settings lookup must never be the reason a page fails to load.
        logger.warning("platform setting %s unreadable; using the default", key, exc_info=True)
        return dict(fallback)
    if row is None or not isinstance(row.value, dict):
        return dict(fallback)
    return {**fallback, **row.value}


async def write_setting(
    uow: SqlUnitOfWork, actor_id: str, key: str, value: dict[str, Any]
) -> None:
    row = await uow.session.scalar(
        sa.select(PlatformSettingORM).where(PlatformSettingORM.key == key)
    )
    if row is None:
        uow.session.add(PlatformSettingORM(key=key, value=value, updated_by=actor_id))
        return
    row.value = value
    row.updated_by = actor_id


async def default_monthly_quota(uow: SqlUnitOfWork, fallback: int) -> int:
    setting = await read_setting(uow, DEFAULT_QUOTA_KEY, {"monthly_tokens": fallback})
    try:
        return max(0, int(setting["monthly_tokens"]))
    except (KeyError, TypeError, ValueError):
        return fallback

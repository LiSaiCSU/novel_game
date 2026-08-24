"""Transactional helpers for the player notification inbox."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.platform import UserNotificationORM
from engine.core.ids import new_id


def add_notification(
    session: AsyncSession,
    *,
    user_id: str,
    kind: str,
    title: str,
    body: str,
    href: str,
) -> UserNotificationORM:
    """Queue a bounded, internal-link notification in the caller's transaction."""

    if not href.startswith("/") or href.startswith("//"):
        raise ValueError("notification href must be an internal path")
    notification = UserNotificationORM(
        id=new_id(),
        user_id=user_id,
        kind=kind[:64],
        title=title.strip()[:160] or "平台通知",
        body=body.strip()[:500],
        href=href[:500],
    )
    session.add(notification)
    return notification

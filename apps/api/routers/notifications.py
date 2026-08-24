"""Player-owned notification inbox endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query

from apps.api.deps import uow_dep
from apps.api.security import Principal, require_csrf, verified_principal
from apps.api.tenancy import set_tenant_context
from database.models.platform import UserNotificationORM
from database.repositories.sql import SqlUnitOfWork

router = APIRouter(prefix="/notifications", tags=["v1-notifications"])


def _view(row: UserNotificationORM) -> dict[str, object]:
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "href": row.href,
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "created_at": row.created_at.isoformat(),
    }


@router.get("")
async def inbox(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    unread_total = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(UserNotificationORM)
            .where(
                UserNotificationORM.user_id == principal.user_id,
                UserNotificationORM.read_at.is_(None),
            )
        )
        or 0
    )
    rows = (
        await uow.session.scalars(
            sa.select(UserNotificationORM)
            .where(UserNotificationORM.user_id == principal.user_id)
            .order_by(UserNotificationORM.read_at.is_not(None), UserNotificationORM.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return {"unread_total": unread_total, "items": [_view(row) for row in rows]}


@router.put("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    row = await uow.session.scalar(
        sa.select(UserNotificationORM)
        .where(
            UserNotificationORM.id == notification_id,
            UserNotificationORM.user_id == principal.user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="notification not found")
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        await uow.commit()
    return _view(row)


@router.post("/read-all")
async def mark_all_read(
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    result = await uow.session.execute(
        sa.update(UserNotificationORM)
        .where(
            UserNotificationORM.user_id == principal.user_id,
            UserNotificationORM.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await uow.commit()
    return {"marked": int(getattr(result, "rowcount", 0) or 0)}

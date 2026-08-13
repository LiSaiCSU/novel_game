"""Administrator-only account, quota and operational controls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from apps.api.deps import uow_dep
from apps.api.security import Principal, require_role_csrf, require_roles
from apps.api.tenancy import set_tenant_context
from database.models.platform import (
    AuditLogORM,
    ContentReleaseORM,
    ModerationCaseORM,
    ProductEventORM,
    UsageLedgerORM,
    UserORM,
    UserRoleORM,
)
from database.repositories.sql import SqlUnitOfWork
from engine.core.ids import new_id

router = APIRouter(prefix="/admin", tags=["v1-admin"])
_ALLOWED_ROLES = frozenset({"player", "creator", "reviewer", "admin"})


def _funnel_stage(key: str, label: str, users: set[str], events: int) -> dict[str, object]:
    return {"key": key, "label": label, "unique_users": len(users), "events": events}


class QuotaWrite(BaseModel):
    monthly_tokens: int = Field(ge=0, le=100_000_000)
    reason: str = Field(min_length=3, max_length=500)


class RolesWrite(BaseModel):
    roles: set[Literal["player", "creator", "reviewer", "admin"]]
    reason: str = Field(min_length=3, max_length=500)


async def _target_user(uow: SqlUnitOfWork, user_id: str) -> UserORM:
    user = await uow.session.get(UserORM, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user


@router.get("/users")
async def list_users(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    query: Annotated[str, Query(max_length=120)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    filters = []
    if query.strip():
        needle = f"%{query.strip()}%"
        filters.append(sa.or_(UserORM.email.ilike(needle), UserORM.display_name.ilike(needle)))
    total = int(
        await uow.session.scalar(sa.select(sa.func.count()).select_from(UserORM).where(*filters))
        or 0
    )
    users = (
        await uow.session.execute(
            sa.select(UserORM)
            .where(*filters)
            .order_by(UserORM.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    ids = [user.id for user in users]
    role_rows = (
        await uow.session.execute(
            sa.select(UserRoleORM.user_id, UserRoleORM.role).where(UserRoleORM.user_id.in_(ids))
        )
    ).all() if ids else []
    roles: dict[str, list[str]] = {user_id: [] for user_id in ids}
    for user_id, role in role_rows:
        roles[user_id].append(role)
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage_rows = (
        await uow.session.execute(
            sa.select(
                UsageLedgerORM.user_id,
                sa.func.coalesce(
                    sa.func.sum(UsageLedgerORM.input_tokens + UsageLedgerORM.output_tokens), 0
                ),
            )
            .where(
                UsageLedgerORM.user_id.in_(ids),
                UsageLedgerORM.created_at >= month_start,
                UsageLedgerORM.provider != "byok",
            )
            .group_by(UsageLedgerORM.user_id)
        )
    ).all() if ids else []
    usage = {user_id: int(tokens) for user_id, tokens in usage_rows}
    return {
        "items": [
            {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "status": user.status,
                "verified": user.email_verified_at is not None,
                "roles": sorted(roles.get(user.id, [])),
                "monthly_quota": user.platform_quota_monthly,
                "monthly_used": usage.get(user.id, 0),
                "created_at": user.created_at,
            }
            for user in users
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.put("/users/{user_id}/quota")
async def set_user_quota(
    user_id: str,
    body: QuotaWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    user = await _target_user(uow, user_id)
    before = user.platform_quota_monthly
    user.platform_quota_monthly = body.monthly_tokens
    uow.session.add(
        AuditLogORM(
            id=new_id(), actor_id=principal.user_id, action="user.quota_changed",
            target_type="user", target_id=user.id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={"before": before, "after": body.monthly_tokens, "reason": body.reason},
        )
    )
    await uow.commit()
    return {"user_id": user.id, "monthly_quota": user.platform_quota_monthly}


@router.put("/users/{user_id}/roles")
async def set_user_roles(
    user_id: str,
    body: RolesWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    await _target_user(uow, user_id)
    requested = set(body.roles)
    requested.add("player")
    if not requested.issubset(_ALLOWED_ROLES):
        raise HTTPException(status_code=422, detail="unknown role")
    current = set(
        (
            await uow.session.execute(
                sa.select(UserRoleORM.role).where(UserRoleORM.user_id == user_id)
            )
        ).scalars().all()
    )
    if user_id == principal.user_id and "admin" not in requested:
        raise HTTPException(status_code=409, detail="administrator cannot remove their own admin role")
    await uow.session.execute(sa.delete(UserRoleORM).where(UserRoleORM.user_id == user_id))
    uow.session.add_all(
        [UserRoleORM(id=new_id(), user_id=user_id, role=role) for role in sorted(requested)]
    )
    uow.session.add(
        AuditLogORM(
            id=new_id(), actor_id=principal.user_id, action="user.roles_changed",
            target_type="user", target_id=user_id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={"before": sorted(current), "after": sorted(requested), "reason": body.reason},
        )
    )
    await uow.commit()
    return {"user_id": user_id, "roles": sorted(requested)}


@router.get("/system")
async def system_summary(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    token_sum = sa.func.coalesce(
        sa.func.sum(UsageLedgerORM.input_tokens + UsageLedgerORM.output_tokens), 0
    )
    users = int(await uow.session.scalar(sa.select(sa.func.count()).select_from(UserORM)) or 0)
    releases = int(
        await uow.session.scalar(sa.select(sa.func.count()).select_from(ContentReleaseORM)) or 0
    )
    pending = int(
        await uow.session.scalar(
            sa.select(sa.func.count()).select_from(ModerationCaseORM).where(
                ModerationCaseORM.status == "pending"
            )
        ) or 0
    )
    tokens = int(await uow.session.scalar(sa.select(token_sum)) or 0)
    failures = int(
        await uow.session.scalar(
            sa.select(sa.func.count()).select_from(UsageLedgerORM).where(
                UsageLedgerORM.success.is_(False)
            )
        ) or 0
    )
    return {
        "users": users,
        "releases": releases,
        "pending_moderation": pending,
        "llm_tokens": tokens,
        "llm_failures": failures,
    }


@router.get("/product-funnel")
async def product_funnel(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> dict[str, object]:
    """Return privacy-safe aggregates; never return event rows or user identities."""
    await set_tenant_context(uow.session, principal.user_id)
    since = datetime.now(UTC) - timedelta(days=days)
    consented_users = int(
        await uow.session.scalar(
            sa.select(sa.func.count()).select_from(UserORM).where(
                UserORM.analytics_consent.is_(True)
            )
        )
        or 0
    )
    rows = (
        await uow.session.execute(
            sa.select(
                ProductEventORM.event_name,
                ProductEventORM.user_id,
                ProductEventORM.event_properties,
                ProductEventORM.occurred_at,
            )
            .where(ProductEventORM.occurred_at >= since)
            .order_by(ProductEventORM.occurred_at.desc())
            .limit(100_001)
        )
    ).all()
    truncated = len(rows) > 100_000
    rows = rows[:100_000]

    stage_users: dict[str, set[str]] = {
        key: set()
        for key in (
            "playthrough_started", "first_action", "third_turn", "ending_selected",
            "project_created", "project_validated", "release_created",
        )
    }
    stage_events = {key: 0 for key in stage_users}
    daily_users: dict[str, set[str]] = {}
    daily_events: dict[str, int] = {}
    for event_name, user_id, properties, occurred_at in rows:
        properties = dict(properties or {})
        stage = str(event_name)
        if stage == "action_completed":
            turn_number = int(properties.get("turn_number", 0) or 0)
            if turn_number >= 1:
                stage_users["first_action"].add(user_id)
                stage_events["first_action"] += 1
            if turn_number >= 3:
                stage_users["third_turn"].add(user_id)
                stage_events["third_turn"] += 1
        elif stage == "project_validated" and properties.get("valid") is not True:
            pass
        elif stage in stage_users:
            stage_users[stage].add(user_id)
            stage_events[stage] += 1
        day = occurred_at.date().isoformat()
        daily_users.setdefault(day, set()).add(user_id)
        daily_events[day] = daily_events.get(day, 0) + 1

    player = [
        _funnel_stage("playthrough_started", "开始正式游戏", stage_users["playthrough_started"], stage_events["playthrough_started"]),
        _funnel_stage("first_action", "完成第一回合", stage_users["first_action"], stage_events["first_action"]),
        _funnel_stage("third_turn", "完成第三回合", stage_users["third_turn"], stage_events["third_turn"]),
        _funnel_stage("ending_selected", "抵达结局", stage_users["ending_selected"], stage_events["ending_selected"]),
    ]
    creator = [
        _funnel_stage("project_created", "创建项目", stage_users["project_created"], stage_events["project_created"]),
        _funnel_stage("project_validated", "通过校验", stage_users["project_validated"], stage_events["project_validated"]),
        _funnel_stage("release_created", "创建版本", stage_users["release_created"], stage_events["release_created"]),
    ]
    daily_active = [
        {"date": day, "users": len(users), "events": daily_events[day]}
        for day, users in sorted(daily_users.items())
    ]
    return {
        "window_days": days,
        "consented_users": consented_users,
        "events_in_window": len(rows),
        "sample_truncated": truncated,
        "player": player,
        "creator": creator,
        "daily_active": daily_active,
    }

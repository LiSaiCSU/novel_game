"""Player support cases with explicit ownership, escalation and audit trails."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from apps.api.deps import settings_dep, uow_dep
from apps.api.notifications import add_notification
from apps.api.rate_limit import rate_limiter
from apps.api.security import (
    Principal,
    require_csrf,
    require_role_csrf,
    require_roles,
    verified_principal,
)
from apps.api.tenancy import set_tenant_context
from database.models.platform import (
    AuditLogORM,
    PlaythroughORM,
    SupportCaseMessageORM,
    SupportCaseORM,
    UserORM,
    UserRoleORM,
)
from database.repositories.sql import SqlUnitOfWork
from engine.core.config import Settings
from engine.core.ids import new_id

router = APIRouter(prefix="/support", tags=["v1-support"])
admin_router = APIRouter(prefix="/admin/support", tags=["v1-admin-support"])

CaseCategory = Literal["account", "billing", "playthrough", "technical", "content", "other"]
CaseStatus = Literal["open", "in_progress", "waiting_user", "resolved", "closed"]
CasePriority = Literal["low", "normal", "high", "urgent"]
_ACTIVE_FOR_PLAYER_REPLY = frozenset({"open", "in_progress", "waiting_user"})
_OPEN_FOR_OPERATIONS = ("open", "in_progress", "waiting_user")


class SupportCaseCreate(BaseModel):
    category: CaseCategory
    subject: str = Field(min_length=3, max_length=140)
    message: str = Field(min_length=5, max_length=4_000)
    playthrough_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def strip_text(self) -> SupportCaseCreate:
        self.subject = self.subject.strip()
        self.message = self.message.strip()
        if len(self.subject) < 3 or len(self.message) < 5:
            raise ValueError("support case subject and message cannot be blank")
        return self


class SupportMessageWrite(BaseModel):
    message: str = Field(min_length=2, max_length=4_000)

    @model_validator(mode="after")
    def strip_message(self) -> SupportMessageWrite:
        self.message = self.message.strip()
        if len(self.message) < 2:
            raise ValueError("support message cannot be blank")
        return self


class SupportCaseUpdate(BaseModel):
    status: CaseStatus | None = None
    priority: CasePriority | None = None
    assigned_to: str | None = Field(default=None, max_length=36)
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def has_a_change(self) -> SupportCaseUpdate:
        if not self.model_fields_set.intersection({"status", "priority", "assigned_to"}):
            raise ValueError("support case update requires a status, priority or assignment change")
        self.reason = self.reason.strip()
        return self


class SupportCaseInspect(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def strip_reason(self) -> SupportCaseInspect:
        self.reason = self.reason.strip()
        if len(self.reason) < 3:
            raise ValueError("support case inspection reason cannot be blank")
        return self


class SupportCaseReply(SupportMessageWrite):
    status: CaseStatus = "waiting_user"
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def strip_reason(self) -> SupportCaseReply:
        self.reason = self.reason.strip()
        if len(self.reason) < 3:
            raise ValueError("support reply reason cannot be blank")
        return self


def _stamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _case_view(
    row: SupportCaseORM,
    *,
    message_count: int | None = None,
    latest_message_at: datetime | None = None,
    include_assignment: bool = False,
) -> dict[str, object]:
    value: dict[str, object] = {
        "id": row.id,
        "playthrough_id": row.playthrough_id,
        "category": row.category,
        "status": row.status,
        "priority": row.priority,
        "subject": row.subject,
        "created_at": _stamp(row.created_at),
        "updated_at": _stamp(row.updated_at),
        "message_count": int(message_count or 0),
        "latest_message_at": _stamp(latest_message_at),
        "player_can_reply": row.status in _ACTIVE_FOR_PLAYER_REPLY,
    }
    if include_assignment:
        value["assigned_to"] = row.assigned_to
    return value


def _message_view(row: SupportCaseMessageORM, *, include_author: bool) -> dict[str, object]:
    value: dict[str, object] = {
        "id": row.id,
        "author_role": row.author_role,
        "body": row.body,
        "created_at": _stamp(row.created_at),
    }
    if include_author:
        value["author_id"] = row.author_id
    return value


def _audit(
    principal: Principal,
    request: Request,
    action: str,
    case: SupportCaseORM,
    details: dict[str, object],
) -> AuditLogORM:
    return AuditLogORM(
        id=new_id(),
        actor_id=principal.user_id,
        action=action,
        target_type="support_case",
        target_id=case.id,
        request_id=str(getattr(request.state, "request_id", "")),
        details=details,
    )


async def _case_for_player(
    uow: SqlUnitOfWork, case_id: str, user_id: str, *, lock: bool = False
) -> SupportCaseORM:
    statement = sa.select(SupportCaseORM).where(
        SupportCaseORM.id == case_id, SupportCaseORM.user_id == user_id
    )
    if lock:
        statement = statement.with_for_update()
    case = await uow.session.scalar(statement)
    if case is None:
        raise HTTPException(status_code=404, detail="support case not found")
    return case


async def _case_for_admin(
    uow: SqlUnitOfWork, case_id: str, *, lock: bool = False
) -> SupportCaseORM:
    statement = sa.select(SupportCaseORM).where(SupportCaseORM.id == case_id)
    if lock:
        statement = statement.with_for_update()
    case = await uow.session.scalar(statement)
    if case is None:
        raise HTTPException(status_code=404, detail="support case not found")
    return case


async def _messages(uow: SqlUnitOfWork, case_id: str) -> list[SupportCaseMessageORM]:
    return list(
        (
            await uow.session.scalars(
                sa.select(SupportCaseMessageORM)
                .where(SupportCaseMessageORM.case_id == case_id)
                .order_by(SupportCaseMessageORM.created_at.asc(), SupportCaseMessageORM.id.asc())
                .limit(200)
            )
        ).all()
    )


async def _operator_view(uow: SqlUnitOfWork, user_id: str | None) -> dict[str, object] | None:
    if not user_id:
        return None
    operator = await uow.session.get(UserORM, user_id)
    if operator is None:
        return None
    return {"id": operator.id, "email": operator.email, "display_name": operator.display_name}


async def _assert_assignable_operator(uow: SqlUnitOfWork, user_id: str) -> None:
    operator = await uow.session.get(UserORM, user_id)
    if operator is None or operator.status != "active":
        raise HTTPException(status_code=422, detail="assigned operator is not active")
    is_operator = await uow.session.scalar(
        sa.select(UserRoleORM.id).where(
            UserRoleORM.user_id == user_id,
            UserRoleORM.role.in_(("admin", "super_admin")),
        )
    )
    if is_operator is None:
        raise HTTPException(status_code=422, detail="assigned operator must be an administrator")


@router.get("/cases")
async def player_cases(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, object]:
    """List only the calling player's support cases and safe metadata."""

    await set_tenant_context(uow.session, principal.user_id)
    message_stats = (
        sa.select(
            SupportCaseMessageORM.case_id.label("case_id"),
            sa.func.count().label("message_count"),
            sa.func.max(SupportCaseMessageORM.created_at).label("latest_message_at"),
        )
        .group_by(SupportCaseMessageORM.case_id)
        .subquery()
    )
    rows = (
        await uow.session.execute(
            sa.select(
                SupportCaseORM,
                sa.func.coalesce(message_stats.c.message_count, 0),
                message_stats.c.latest_message_at,
            )
            .outerjoin(message_stats, message_stats.c.case_id == SupportCaseORM.id)
            .where(SupportCaseORM.user_id == principal.user_id)
            .order_by(SupportCaseORM.updated_at.desc(), SupportCaseORM.id.desc())
            .limit(limit)
        )
    ).all()
    return {
        "items": [
            _case_view(case, message_count=int(count or 0), latest_message_at=latest)
            for case, count, latest in rows
        ]
    }


@router.post("/cases", status_code=201)
async def create_player_case(
    body: SupportCaseCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    """Open a narrowly scoped case without copying private game data."""

    await set_tenant_context(uow.session, principal.user_id)
    await rate_limiter.check(
        f"support-case-create:{principal.user_id}", 5, 3_600, redis_url=settings.redis_url
    )
    if body.playthrough_id:
        playthrough = await uow.session.scalar(
            sa.select(PlaythroughORM.id).where(
                PlaythroughORM.id == body.playthrough_id,
                PlaythroughORM.user_id == principal.user_id,
            )
        )
        if playthrough is None:
            raise HTTPException(status_code=404, detail="playthrough not found")
    case = SupportCaseORM(
        id=new_id(),
        user_id=principal.user_id,
        playthrough_id=body.playthrough_id,
        category=body.category,
        status="open",
        priority="normal",
        subject=body.subject,
    )
    message = SupportCaseMessageORM(
        id=new_id(),
        case_id=case.id,
        author_id=principal.user_id,
        author_role="player",
        body=body.message,
    )
    uow.session.add_all([case, message])
    uow.session.add(
        _audit(
            principal,
            request,
            "support.case_created",
            case,
            {"category": case.category, "playthrough_attached": bool(case.playthrough_id)},
        )
    )
    await uow.commit()
    return {**_case_view(case, message_count=1, latest_message_at=message.created_at), "messages": [_message_view(message, include_author=False)]}


@router.get("/cases/{case_id}")
async def player_case_detail(
    case_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    case = await _case_for_player(uow, case_id, principal.user_id)
    messages = await _messages(uow, case.id)
    return {
        **_case_view(case, message_count=len(messages), latest_message_at=messages[-1].created_at if messages else None),
        "messages": [_message_view(message, include_author=False) for message in messages],
    }


@router.post("/cases/{case_id}/messages", status_code=201)
async def reply_to_player_case(
    case_id: str,
    body: SupportMessageWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    await rate_limiter.check(
        f"support-case-reply:{principal.user_id}", 12, 3_600, redis_url=settings.redis_url
    )
    case = await _case_for_player(uow, case_id, principal.user_id)
    if case.status not in _ACTIVE_FOR_PLAYER_REPLY:
        raise HTTPException(status_code=409, detail="support case is not accepting replies")
    message = SupportCaseMessageORM(
        id=new_id(),
        case_id=case.id,
        author_id=principal.user_id,
        author_role="player",
        body=body.message,
    )
    uow.session.add(message)
    uow.session.add(_audit(principal, request, "support.case_replied", case, {"author": "player"}))
    await uow.commit()
    return _message_view(message, include_author=False)


@admin_router.get("/summary")
async def support_summary(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Return aggregate queue health without exposing case content."""

    await set_tenant_context(uow.session, principal.user_id)
    by_status = (
        await uow.session.execute(
            sa.select(SupportCaseORM.status, sa.func.count())
            .group_by(SupportCaseORM.status)
            .order_by(SupportCaseORM.status)
        )
    ).all()
    by_priority = (
        await uow.session.execute(
            sa.select(SupportCaseORM.priority, sa.func.count())
            .group_by(SupportCaseORM.priority)
            .order_by(SupportCaseORM.priority)
        )
    ).all()
    now = datetime.now(UTC)
    unassigned = int(
        await uow.session.scalar(
            sa.select(sa.func.count()).select_from(SupportCaseORM).where(
                SupportCaseORM.status.in_(_OPEN_FOR_OPERATIONS), SupportCaseORM.assigned_to.is_(None)
            )
        )
        or 0
    )
    oldest_open_at = await uow.session.scalar(
        sa.select(sa.func.min(SupportCaseORM.created_at)).where(
            SupportCaseORM.status.in_(_OPEN_FOR_OPERATIONS)
        )
    )
    return {
        "window_hours": 24,
        "created_24h": int(
            await uow.session.scalar(
                sa.select(sa.func.count()).select_from(SupportCaseORM).where(
                    SupportCaseORM.created_at >= now - timedelta(hours=24)
                )
            )
            or 0
        ),
        "unassigned_open": unassigned,
        "oldest_open_at": _stamp(oldest_open_at),
        "by_status": {str(status): int(count) for status, count in by_status},
        "by_priority": {str(priority): int(count) for priority, count in by_priority},
    }


@admin_router.get("/operators")
async def support_operators(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    rows = (
        await uow.session.execute(
            sa.select(UserORM)
            .join(UserRoleORM, UserRoleORM.user_id == UserORM.id)
            .where(UserORM.status == "active", UserRoleORM.role.in_(("admin", "super_admin")))
            .distinct()
            .order_by(UserORM.display_name.asc(), UserORM.email.asc())
        )
    ).scalars().all()
    return {
        "items": [
            {"id": user.id, "email": user.email, "display_name": user.display_name}
            for user in rows
        ]
    }


@admin_router.get("/cases")
async def admin_cases(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    status: CaseStatus | None = None,
    priority: CasePriority | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    message_stats = (
        sa.select(
            SupportCaseMessageORM.case_id.label("case_id"),
            sa.func.count().label("message_count"),
            sa.func.max(SupportCaseMessageORM.created_at).label("latest_message_at"),
        )
        .group_by(SupportCaseMessageORM.case_id)
        .subquery()
    )
    conditions: list[sa.ColumnElement[bool]] = []
    if status:
        conditions.append(SupportCaseORM.status == status)
    if priority:
        conditions.append(SupportCaseORM.priority == priority)
    rows = (
        await uow.session.execute(
            sa.select(
                SupportCaseORM,
                UserORM,
                sa.func.coalesce(message_stats.c.message_count, 0),
                message_stats.c.latest_message_at,
            )
            .join(UserORM, UserORM.id == SupportCaseORM.user_id)
            .outerjoin(message_stats, message_stats.c.case_id == SupportCaseORM.id)
            .where(*conditions)
            .order_by(
                sa.case((SupportCaseORM.priority == "urgent", 0), (SupportCaseORM.priority == "high", 1), else_=2),
                SupportCaseORM.updated_at.desc(),
            )
            .limit(limit)
        )
    ).all()
    return {
        "items": [
            {
                **_case_view(
                    case,
                    message_count=int(count or 0),
                    latest_message_at=latest,
                    include_assignment=True,
                ),
                "player": {"id": user.id, "email": user.email, "display_name": user.display_name},
            }
            for case, user, count, latest in rows
        ]
    }


@admin_router.post("/cases/{case_id}")
async def admin_case_detail(
    case_id: str,
    body: SupportCaseInspect,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Reveal private case correspondence only through a recorded access event."""

    await set_tenant_context(uow.session, principal.user_id)
    case = await _case_for_admin(uow, case_id)
    player = await uow.session.get(UserORM, case.user_id)
    messages = await _messages(uow, case.id)
    uow.session.add(
        _audit(
            principal,
            request,
            "support.case_inspected",
            case,
            {"reason": body.reason, "message_count": len(messages)},
        )
    )
    await uow.commit()
    return {
        **_case_view(
            case,
            message_count=len(messages),
            latest_message_at=messages[-1].created_at if messages else None,
            include_assignment=True,
        ),
        "player": (
            {"id": player.id, "email": player.email, "display_name": player.display_name}
            if player is not None
            else None
        ),
        "assigned_operator": await _operator_view(uow, case.assigned_to),
        "messages": [_message_view(message, include_author=True) for message in messages],
    }


@admin_router.put("/cases/{case_id}")
async def update_case(
    case_id: str,
    body: SupportCaseUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Assign and change a case without editing player or operator messages."""

    await set_tenant_context(uow.session, principal.user_id)
    case = await _case_for_admin(uow, case_id, lock=True)
    before = {"status": case.status, "priority": case.priority, "assigned_to": case.assigned_to}
    if "assigned_to" in body.model_fields_set and body.assigned_to:
        await _assert_assignable_operator(uow, body.assigned_to)
    if "status" in body.model_fields_set:
        case.status = body.status or case.status
    if "priority" in body.model_fields_set:
        case.priority = body.priority or case.priority
    if "assigned_to" in body.model_fields_set:
        case.assigned_to = body.assigned_to
    case.updated_at = datetime.now(UTC)
    after = {"status": case.status, "priority": case.priority, "assigned_to": case.assigned_to}
    uow.session.add(
        _audit(principal, request, "support.case_updated", case, {"before": before, "after": after, "reason": body.reason})
    )
    await uow.commit()
    return {
        **_case_view(case, include_assignment=True),
        "assigned_operator": await _operator_view(uow, case.assigned_to),
    }


@admin_router.post("/cases/{case_id}/messages", status_code=201)
async def reply_to_case(
    case_id: str,
    body: SupportCaseReply,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Reply visibly to the player and move the case to an explicit state."""

    await set_tenant_context(uow.session, principal.user_id)
    case = await _case_for_admin(uow, case_id, lock=True)
    previous_status = case.status
    message = SupportCaseMessageORM(
        id=new_id(),
        case_id=case.id,
        author_id=principal.user_id,
        author_role="admin",
        body=body.message,
    )
    case.status = body.status
    if case.assigned_to is None:
        case.assigned_to = principal.user_id
    case.updated_at = datetime.now(UTC)
    uow.session.add(message)
    add_notification(
        uow.session,
        user_id=case.user_id,
        kind="support.reply",
        title="支持团队已回复你的请求",
        body=case.subject,
        href="/support",
    )
    uow.session.add(
        _audit(
            principal,
            request,
            "support.case_replied",
            case,
            {"from_status": previous_status, "to_status": case.status, "reason": body.reason},
        )
    )
    await uow.commit()
    return {
        "message": _message_view(message, include_author=True),
        "case": _case_view(case, include_assignment=True),
    }

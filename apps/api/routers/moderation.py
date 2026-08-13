"""Reviewer queues, report decisions, emergency takedown and audit reads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from apps.api.deps import uow_dep
from apps.api.security import Principal, require_role_csrf, require_roles
from apps.api.tenancy import set_tenant_context
from database.models.platform import (
    AuditLogORM,
    ContentReleaseORM,
    ModerationCaseORM,
    ProjectORM,
    ReportORM,
)
from database.repositories.sql import SqlUnitOfWork
from engine.core.ids import new_id

router = APIRouter(prefix="/creator", tags=["v1-moderation"])


class ReviewDecision(BaseModel):
    decision: Literal["approved", "rejected", "withdrawn"]
    reason: str = Field(min_length=3, max_length=2000)


class ReportDecision(BaseModel):
    decision: Literal["investigating", "resolved", "dismissed", "takedown"]
    note: str = Field(min_length=3, max_length=2000)


@router.get("/reviews")
async def review_queue(
    principal: Annotated[Principal, Depends(require_roles("reviewer", "admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> list[dict[str, Any]]:
    await set_tenant_context(uow.session, principal.user_id)
    rows = (
        await uow.session.execute(
            sa.select(ModerationCaseORM, ContentReleaseORM)
            .join(ContentReleaseORM, ContentReleaseORM.id == ModerationCaseORM.release_id)
            .where(ModerationCaseORM.status == "pending")
            .order_by(ModerationCaseORM.created_at)
        )
    ).all()
    return [
        {
            "case_id": case.id,
            "release_id": release.id,
            "title": release.title,
            "rating": release.rating,
            "evidence": case.evidence,
            "submitted_at": case.created_at,
        }
        for case, release in rows
    ]


@router.post("/reviews/{case_id}")
async def decide_review(
    case_id: str,
    body: ReviewDecision,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("reviewer", "admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, str]:
    await set_tenant_context(uow.session, principal.user_id)
    case = await uow.session.get(ModerationCaseORM, case_id)
    if case is None or case.status != "pending":
        raise HTTPException(status_code=404, detail="pending review not found")
    release = await uow.session.get(ContentReleaseORM, case.release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    case.status = body.decision
    case.reviewer_id = principal.user_id
    case.decision_reason = body.reason
    release.moderation_status = body.decision
    if body.decision == "approved":
        release.published_at = datetime.now(UTC)
        release.withdrawn_at = None
        project = await uow.session.get(ProjectORM, release.project_id)
        if project is not None:
            project.status = "published"
    elif body.decision == "withdrawn":
        release.withdrawn_at = datetime.now(UTC)
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="moderation.decided",
            target_type="content_release",
            target_id=release.id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={"case_id": case.id, "decision": body.decision, "reason": body.reason},
        )
    )
    await uow.commit()
    return {"status": body.decision}


@router.get("/reports")
async def report_queue(
    principal: Annotated[Principal, Depends(require_roles("reviewer", "admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> list[dict[str, Any]]:
    await set_tenant_context(uow.session, principal.user_id)
    rows = (
        await uow.session.execute(
            sa.select(ReportORM, ContentReleaseORM)
            .join(ContentReleaseORM, ContentReleaseORM.id == ReportORM.release_id)
            .where(ReportORM.status.in_(("open", "investigating")))
            .order_by(ReportORM.created_at)
        )
    ).all()
    return [
        {
            "id": report.id,
            "release_id": release.id,
            "title": release.title,
            "category": report.category,
            "details": report.details,
            "status": report.status,
            "created_at": report.created_at,
        }
        for report, release in rows
    ]


@router.post("/reports/{report_id}")
async def decide_report(
    report_id: str,
    body: ReportDecision,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("reviewer", "admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, str]:
    await set_tenant_context(uow.session, principal.user_id)
    report = await uow.session.get(ReportORM, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    release = await uow.session.get(ContentReleaseORM, report.release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    report.status = body.decision
    if body.decision == "takedown":
        release.withdrawn_at = datetime.now(UTC)
        release.moderation_status = "withdrawn"
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="report.decided",
            target_type="content_release",
            target_id=release.id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={"report_id": report.id, "decision": body.decision, "note": body.note},
        )
    )
    await uow.commit()
    return {"status": body.decision}


@router.get("/audit-logs")
async def audit_logs(
    principal: Annotated[Principal, Depends(require_roles("reviewer", "admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    limit: int = 100,
) -> list[dict[str, Any]]:
    del principal
    rows = (
        (
            await uow.session.execute(
                sa.select(AuditLogORM)
                .order_by(AuditLogORM.created_at.desc())
                .limit(max(1, min(limit, 500)))
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "request_id": row.request_id,
            "details": row.details,
            "created_at": row.created_at,
        }
        for row in rows
    ]

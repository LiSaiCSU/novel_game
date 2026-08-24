"""Administrator-only account, quota and operational controls."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from apps.api.deps import settings_dep, uow_dep
from apps.api.llm_config import (
    PLATFORM_LLM_CONFIG_ID,
    SUPPORTED_PLATFORM_PROVIDERS,
    load_platform_llm_config,
    normalize_public_api_base_url,
    platform_llm_view,
)
from apps.api.platform_settings import (
    ANNOUNCEMENT_KEY,
    DEFAULT_QUOTA_FALLBACK,
    DEFAULT_QUOTA_KEY,
    EMPTY_ANNOUNCEMENT,
    read_setting,
    write_setting,
)
from apps.api.rate_limit import rate_limiter
from apps.api.security import Principal, SecretBox, require_role_csrf, require_roles
from apps.api.tenancy import set_tenant_context
from apps.worker.tasks import scrub_account
from database.models.orm import GameSessionORM
from database.models.platform import (
    AuditLogORM,
    AuthSessionORM,
    ContentReleaseORM,
    ModerationCaseORM,
    PlatformLlmConfigORM,
    PlaythroughORM,
    ProductEventORM,
    SuperAdminApprovalORM,
    SupportCaseORM,
    UsageLedgerORM,
    UserORM,
    UserRoleORM,
    WalletHoldORM,
)
from database.repositories.sql import SqlUnitOfWork
from engine.core.config import Settings
from engine.core.ids import new_id
from engine.core.logging import get_logger
from engine.core.types import LLMRole
from engine.llm.provider import LLMMessage, LLMRequest
from engine.llm.providers import build_provider
from engine.llm.router import ModelRouter

router = APIRouter(prefix="/admin", tags=["v1-admin"])
_ALLOWED_ROLES = frozenset({"player", "creator", "reviewer", "admin", "super_admin"})
logger = get_logger("admin")


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite development timestamps before a policy comparison."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _funnel_stage(key: str, label: str, users: set[str], events: int) -> dict[str, object]:
    return {"key": key, "label": label, "unique_users": len(users), "events": events}


class QuotaWrite(BaseModel):
    monthly_tokens: int = Field(ge=0, le=100_000_000)
    reason: str = Field(min_length=3, max_length=500)


class RolesWrite(BaseModel):
    roles: set[Literal["player", "creator", "reviewer", "admin"]]
    reason: str = Field(min_length=3, max_length=500)


class SuperAdminWrite(BaseModel):
    enabled: bool
    reason: str = Field(min_length=3, max_length=500)


class SuperAdminApprovalDecisionWrite(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class BulkQuotaWrite(BaseModel):
    """Set one quota across a whole population of accounts.

    ``expect_users`` is required and must match the number of accounts the
    filter actually selects. Changing every account on the platform is a
    reasonable thing to want and a terrible thing to do by accident, so the
    caller has to have looked at the count first.
    """

    monthly_tokens: int = Field(ge=0, le=100_000_000)
    reason: str = Field(min_length=3, max_length=500)
    scope: Literal["all", "role", "search"] = "all"
    role: Literal["player", "creator", "reviewer", "admin"] | None = None
    query: str = Field(default="", max_length=120)
    expect_users: int = Field(ge=0, le=1_000_000)

    @model_validator(mode="after")
    def scope_matches_filter(self) -> BulkQuotaWrite:
        if self.scope == "role" and not self.role:
            raise ValueError("role scope requires a role")
        if self.scope == "search" and not self.query.strip():
            raise ValueError("search scope requires a query")
        return self


class AccountActionWrite(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class SuspendWrite(AccountActionWrite):
    suspended: bool


class DeleteUserWrite(AccountActionWrite):
    #: The address, typed out. An id is easy to paste from the wrong row.
    confirm_email: str = Field(min_length=3, max_length=320)


class DefaultQuotaWrite(BaseModel):
    monthly_tokens: int = Field(ge=0, le=100_000_000)
    reason: str = Field(min_length=3, max_length=500)


class AnnouncementWrite(BaseModel):
    message: str = Field(default="", max_length=500)
    level: Literal["info", "warning", "maintenance"] = "info"
    active: bool = False
    reason: str = Field(min_length=3, max_length=500)


class TakedownWrite(AccountActionWrite):
    restore: bool = False


class PlatformLlmWrite(BaseModel):
    enabled: bool = True
    provider: Literal["openai", "anthropic", "compatible"]
    # Legacy aliases remain accepted throughout the v1 compatibility window.
    model: str = Field(default="", max_length=160)
    base_url: str = Field(default="", max_length=500)
    api_key: str | None = Field(default=None, min_length=8, max_length=1000)
    extra_body: dict[str, Any] = Field(default_factory=dict)
    narrative_model: str = Field(default="", max_length=160)
    narrative_extra_body: dict[str, Any] | None = None
    reasoning_enabled: bool = False
    reasoning_model: str = Field(default="", max_length=160)
    reasoning_extra_body: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def validate_configuration(self) -> PlatformLlmWrite:
        self.narrative_model = (self.narrative_model or self.model).strip()
        if not self.narrative_model:
            raise ValueError("必须填写叙事模型名称")
        self.model = self.narrative_model
        if self.narrative_extra_body is None:
            self.narrative_extra_body = dict(self.extra_body)
        self.extra_body = dict(self.narrative_extra_body)
        self.reasoning_model = self.reasoning_model.strip()
        if self.reasoning_enabled and not self.reasoning_model:
            raise ValueError("启用独立推理模型时必须填写模型名称")
        self.base_url = normalize_public_api_base_url(
            self.base_url, required=self.provider == "compatible"
        )
        for label, value in (
            ("叙事模型", self.extra_body),
            ("推理模型", self.reasoning_extra_body),
        ):
            if len(json.dumps(value, ensure_ascii=False)) > 8_000:
                raise ValueError(f"{label}附加请求参数不能超过 8 KB")
            if {"model", "messages", "stream"}.intersection(value):
                raise ValueError(f"{label}附加请求参数不能覆盖 model、messages 或 stream")
        return self


def _audit_llm_view(view: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in view.items() if key not in {"updated_at", "key_hint"}}


async def _target_user(uow: SqlUnitOfWork, user_id: str) -> UserORM:
    user = await uow.session.get(UserORM, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user


@router.get("/llm-config")
async def get_platform_llm_config(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    """Return operational model settings without ever returning the secret."""
    await set_tenant_context(uow.session, principal.user_id)
    _effective, row = await load_platform_llm_config(uow.session, settings)
    return platform_llm_view(settings, row)


@router.put("/llm-config")
async def update_platform_llm_config(
    body: PlatformLlmWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    if body.provider not in SUPPORTED_PLATFORM_PROVIDERS:
        raise HTTPException(status_code=422, detail="unsupported platform model provider")
    row = await uow.session.get(PlatformLlmConfigORM, PLATFORM_LLM_CONFIG_ID)
    before = platform_llm_view(settings, row)
    if row is None:
        row = PlatformLlmConfigORM(id=PLATFORM_LLM_CONFIG_ID)
        uow.session.add(row)
    row.enabled = body.enabled
    row.provider = body.provider
    row.model = body.narrative_model
    row.base_url = body.base_url
    row.extra_body = dict(body.narrative_extra_body or {})
    row.reasoning_enabled = body.reasoning_enabled
    row.reasoning_model = body.reasoning_model
    row.reasoning_extra_body = dict(body.reasoning_extra_body)
    row.updated_by = principal.user_id
    if body.api_key is not None:
        try:
            row.encrypted_secret = SecretBox(settings.credential_encryption_key).encrypt(
                body.api_key
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=503, detail="platform credential encryption is not configured"
            ) from exc
        row.key_hint = f"…{body.api_key[-4:]}"
    await uow.session.flush()
    after = platform_llm_view(settings, row)
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="platform_llm.config_changed",
            target_type="platform_llm_config",
            target_id=row.id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={
                "before": _audit_llm_view(before),
                "after": _audit_llm_view(after),
                "key_rotated": body.api_key is not None,
                "reason": body.reason,
            },
        )
    )
    await uow.commit()
    return platform_llm_view(settings, row)


@router.post("/llm-config/test")
async def test_platform_llm_config(
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
    profile: Literal["narrative", "reasoning"] = "narrative",
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    await rate_limiter.check(
        f"platform-llm-test:{principal.user_id}", 3, 60, redis_url=settings.redis_url
    )
    try:
        effective, row = await load_platform_llm_config(uow.session, settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=503, detail="platform credential cannot be decrypted"
        ) from exc
    view = platform_llm_view(settings, row)
    if not view["enabled"]:
        raise HTTPException(status_code=409, detail="platform model is disabled")
    role = LLMRole.NARRATIVE if profile == "narrative" else LLMRole.DIRECTOR
    choice = ModelRouter(effective).choose(role)
    if not choice.model.strip():
        label = "叙事" if profile == "narrative" else "推理"
        raise HTTPException(status_code=409, detail=f"{label}模型名称未配置")
    provider = build_provider(
        effective.model_copy(update={"llm_timeout_seconds": min(effective.llm_timeout_seconds, 20)})
    )
    if not provider.available:
        raise HTTPException(status_code=409, detail="platform model credential is missing")
    try:
        raw_extra_body = (
            effective.llm_extra_body
            if profile == "narrative"
            else effective.llm_reasoning_extra_body or effective.llm_extra_body
        )
        extra_body = json.loads(raw_extra_body or "{}")
        response = await provider.generate_text(
            LLMRequest(
                model=choice.model,
                system="Return only valid JSON.",
                messages=[LLMMessage(content='Return {"status":"ok"}.')],
                temperature=0,
                max_output_tokens=96 if profile == "narrative" else 1024,
                json_mode=True,
                extra_body=extra_body if isinstance(extra_body, dict) else {},
            )
        )
        if not response.text.strip():
            raise RuntimeError("empty model response")
    except Exception as exc:
        logger.warning("platform LLM connection test failed error_type=%s", type(exc).__name__)
        uow.session.add(
            AuditLogORM(
                id=new_id(),
                actor_id=principal.user_id,
                action="platform_llm.connection_test_failed",
                target_type="platform_llm_config",
                target_id=PLATFORM_LLM_CONFIG_ID,
                request_id=str(getattr(request.state, "request_id", "")),
                details={
                    "profile": profile,
                    "provider": view["provider"],
                    "model": choice.model,
                },
            )
        )
        await uow.commit()
        raise HTTPException(
            status_code=502, detail="模型连接失败，请检查 API 地址、密钥和模型名称"
        ) from exc
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="platform_llm.connection_test_succeeded",
            target_type="platform_llm_config",
            target_id=PLATFORM_LLM_CONFIG_ID,
            request_id=str(getattr(request.state, "request_id", "")),
            details={
                "profile": profile,
                "provider": view["provider"],
                "model": response.model or choice.model,
                "latency_ms": response.latency_ms,
            },
        )
    )
    await uow.commit()
    return {
        "status": "ok",
        "profile": profile,
        "provider": view["provider"],
        "model": response.model or choice.model,
        "latency_ms": response.latency_ms,
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
    }


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
        (
            await uow.session.execute(
                sa.select(UserORM)
                .where(*filters)
                .order_by(UserORM.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    ids = [user.id for user in users]
    role_rows = (
        (
            await uow.session.execute(
                sa.select(UserRoleORM.user_id, UserRoleORM.role).where(UserRoleORM.user_id.in_(ids))
            )
        ).all()
        if ids
        else []
    )
    roles: dict[str, list[str]] = {user_id: [] for user_id in ids}
    for user_id, role in role_rows:
        roles[user_id].append(role)
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage_rows = (
        (
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
        ).all()
        if ids
        else []
    )
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
            id=new_id(),
            actor_id=principal.user_id,
            action="user.quota_changed",
            target_type="user",
            target_id=user.id,
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
    target = await uow.session.scalar(
        sa.select(UserORM).where(UserORM.id == user_id).with_for_update()
    )
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    requested: set[str] = set(body.roles)
    requested.add("player")
    if not requested.issubset(_ALLOWED_ROLES):
        raise HTTPException(status_code=422, detail="unknown role")
    current = set(
        (
            await uow.session.execute(
                sa.select(UserRoleORM.role).where(UserRoleORM.user_id == user_id)
            )
    )
        .scalars()
        .all()
    )
    if "super_admin" in current:
        if not principal.has_role("super_admin"):
            raise HTTPException(status_code=403, detail="super administrator role is protected")
        # Generic role editing cannot silently demote a break-glass account.
        # The dedicated endpoint below has a last-super-admin guard.
        requested.add("super_admin")
        requested.add("admin")
    if user_id == principal.user_id and "admin" not in requested:
        raise HTTPException(
            status_code=409, detail="administrator cannot remove their own admin role"
        )
    await uow.session.execute(sa.delete(UserRoleORM).where(UserRoleORM.user_id == user_id))
    uow.session.add_all(
        [UserRoleORM(id=new_id(), user_id=user_id, role=role) for role in sorted(requested)]
    )
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="user.roles_changed",
            target_type="user",
            target_id=user_id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={"before": sorted(current), "after": sorted(requested), "reason": body.reason},
        )
    )
    await uow.commit()
    return {"user_id": user_id, "roles": sorted(requested)}


@router.get("/governance/super-admins")
async def list_super_admins(
    principal: Annotated[Principal, Depends(require_roles("super_admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """List the deliberately small break-glass administrator set."""

    await set_tenant_context(uow.session, principal.user_id)
    rows = (
        await uow.session.execute(
            sa.select(UserORM, UserRoleORM.created_at)
            .join(UserRoleORM, UserRoleORM.user_id == UserORM.id)
            .where(UserRoleORM.role == "super_admin")
            .order_by(UserRoleORM.created_at.asc(), UserORM.email.asc())
        )
    ).all()
    requester = sa.orm.aliased(UserORM)
    target = sa.orm.aliased(UserORM)
    approvals = (
        await uow.session.execute(
            sa.select(SuperAdminApprovalORM, requester.email, target.email)
            .join(requester, requester.id == SuperAdminApprovalORM.requester_id)
            .join(target, target.id == SuperAdminApprovalORM.target_user_id)
            .where(
                SuperAdminApprovalORM.status == "pending",
                SuperAdminApprovalORM.expires_at > datetime.now(UTC),
            )
            .order_by(SuperAdminApprovalORM.created_at.asc())
        )
    ).all()
    return {
        "items": [
            {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "status": user.status,
                "granted_at": granted_at,
            }
            for user, granted_at in rows
        ],
        "pending_approvals": [
            {
                "id": approval.id,
                "requester_id": approval.requester_id,
                "requester_email": requester_email,
                "target_user_id": approval.target_user_id,
                "target_email": target_email,
                "requested_enabled": approval.requested_enabled,
                "reason": approval.request_reason,
                "expires_at": approval.expires_at,
                "created_at": approval.created_at,
            }
            for approval, requester_email, target_email in approvals
        ],
        "current_user_id": principal.user_id,
        "mfa_required": True,
    }


@router.put("/users/{user_id}/super-admin")
async def set_super_admin(
    user_id: str,
    body: SuperAdminWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("super_admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Open a dual-control request; it never changes a role by itself."""

    await set_tenant_context(uow.session, principal.user_id)
    user = await uow.session.scalar(
        sa.select(UserORM).where(UserORM.id == user_id).with_for_update()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if user_id == principal.user_id:
        raise HTTPException(status_code=409, detail="super administrator cannot request a change to own role")
    if user.status != "active":
        raise HTTPException(status_code=409, detail="only an active account can be a super administrator")
    pending = await uow.session.scalar(
        sa.select(SuperAdminApprovalORM)
        .where(
            SuperAdminApprovalORM.target_user_id == user_id,
            SuperAdminApprovalORM.status == "pending",
        )
        .with_for_update()
    )
    now = datetime.now(UTC)
    if pending is not None and _as_utc(pending.expires_at) <= now:
        pending.status = "expired"
        pending.decision_reason = "请求未在时限内获得复核"
        await uow.session.flush()
        pending = None
    if pending is not None:
        if pending.requested_enabled == body.enabled:
            return {
                "id": pending.id,
                "status": pending.status,
                "expires_at": pending.expires_at,
                "requested_enabled": pending.requested_enabled,
                "idempotent_replay": True,
            }
        raise HTTPException(status_code=409, detail="a different super administrator request is pending")
    approval = SuperAdminApprovalORM(
        id=new_id(),
        requester_id=principal.user_id,
        target_user_id=user_id,
        requested_enabled=body.enabled,
        request_reason=body.reason,
        status="pending",
        expires_at=now + timedelta(hours=24),
    )
    uow.session.add(approval)
    uow.session.add(
        _audit(
            principal,
            request,
            "super_admin.approval_requested",
            approval.id,
            {
                "target_user_id": user_id,
                "requested_enabled": body.enabled,
                "reason": body.reason,
                "expires_at": approval.expires_at.isoformat(),
            },
            target_type="super_admin_approval",
        )
    )
    await uow.commit()
    return {
        "id": approval.id,
        "status": approval.status,
        "expires_at": approval.expires_at,
        "requested_enabled": approval.requested_enabled,
        "idempotent_replay": False,
    }


async def _pending_super_admin_approval(
    uow: SqlUnitOfWork, approval_id: str, principal: Principal
) -> SuperAdminApprovalORM:
    approval = await uow.session.scalar(
        sa.select(SuperAdminApprovalORM)
        .where(SuperAdminApprovalORM.id == approval_id)
        .with_for_update()
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="super administrator approval not found")
    if approval.requester_id == principal.user_id:
        raise HTTPException(status_code=409, detail="requester cannot review own super administrator request")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="super administrator approval is not pending")
    if _as_utc(approval.expires_at) <= datetime.now(UTC):
        approval.status = "expired"
        approval.decision_reason = "请求未在时限内获得复核"
        await uow.commit()
        raise HTTPException(status_code=409, detail="super administrator approval has expired")
    return approval


@router.post("/governance/super-admin-approvals/{approval_id}/approve")
async def approve_super_admin_change(
    approval_id: str,
    body: SuperAdminApprovalDecisionWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("super_admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """A second super administrator approves and executes an elevation change."""

    await set_tenant_context(uow.session, principal.user_id)
    approval = await _pending_super_admin_approval(uow, approval_id, principal)
    target = await uow.session.scalar(
        sa.select(UserORM).where(UserORM.id == approval.target_user_id).with_for_update()
    )
    if target is None or target.status != "active":
        raise HTTPException(status_code=409, detail="approval target is not an active account")
    super_roles = (
        await uow.session.scalars(
            sa.select(UserRoleORM).where(UserRoleORM.role == "super_admin").with_for_update()
        )
    ).all()
    current_super_ids = {role.user_id for role in super_roles}
    idempotent_replay = False
    if approval.requested_enabled:
        roles = set(
            (
                await uow.session.scalars(
                    sa.select(UserRoleORM.role).where(UserRoleORM.user_id == target.id)
                )
            ).all()
        )
        added = {"admin", "super_admin"} - roles
        uow.session.add_all(
            UserRoleORM(id=new_id(), user_id=target.id, role=role) for role in added
        )
        role_action = "user.super_admin_granted"
        idempotent_replay = not added
    else:
        if target.id not in current_super_ids:
            role_action = "user.super_admin_revoke_idempotent"
            idempotent_replay = True
        else:
            if len(current_super_ids) <= 1:
                raise HTTPException(status_code=409, detail="at least one super administrator is required")
            await uow.session.execute(
                sa.delete(UserRoleORM).where(
                    UserRoleORM.user_id == target.id, UserRoleORM.role == "super_admin"
                )
            )
            role_action = "user.super_admin_revoked"
    approval.status = "approved"
    approval.approver_id = principal.user_id
    approval.decision_reason = body.reason
    approval.executed_at = datetime.now(UTC)
    uow.session.add(
        _audit(
            principal,
            request,
            "super_admin.approval_approved",
            approval.id,
            {
                "target_user_id": target.id,
                "requested_enabled": approval.requested_enabled,
                "requester_id": approval.requester_id,
                "reason": body.reason,
            },
            target_type="super_admin_approval",
        )
    )
    uow.session.add(
        _audit(
            principal,
            request,
            role_action,
            target.id,
            {
                "approval_id": approval.id,
                "requester_id": approval.requester_id,
                "approval_reason": body.reason,
                "request_reason": approval.request_reason,
            },
        )
    )
    await uow.commit()
    return {
        "id": approval.id,
        "status": approval.status,
        "user_id": target.id,
        "super_admin": approval.requested_enabled,
        "idempotent_replay": idempotent_replay,
    }


@router.post("/governance/super-admin-approvals/{approval_id}/reject")
async def reject_super_admin_change(
    approval_id: str,
    body: SuperAdminApprovalDecisionWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("super_admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """A second super administrator rejects an unexecuted role-change request."""

    await set_tenant_context(uow.session, principal.user_id)
    approval = await _pending_super_admin_approval(uow, approval_id, principal)
    approval.status = "rejected"
    approval.approver_id = principal.user_id
    approval.decision_reason = body.reason
    uow.session.add(
        _audit(
            principal,
            request,
            "super_admin.approval_rejected",
            approval.id,
            {
                "target_user_id": approval.target_user_id,
                "requested_enabled": approval.requested_enabled,
                "requester_id": approval.requester_id,
                "reason": body.reason,
            },
            target_type="super_admin_approval",
        )
    )
    await uow.commit()
    return {"id": approval.id, "status": approval.status}


@router.post("/governance/super-admin-approvals/{approval_id}/cancel")
async def cancel_super_admin_change(
    approval_id: str,
    body: SuperAdminApprovalDecisionWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("super_admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """The requester can cancel, but never approve, their own request."""

    await set_tenant_context(uow.session, principal.user_id)
    approval = await uow.session.scalar(
        sa.select(SuperAdminApprovalORM)
        .where(SuperAdminApprovalORM.id == approval_id)
        .with_for_update()
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="super administrator approval not found")
    if approval.requester_id != principal.user_id:
        raise HTTPException(status_code=403, detail="only requester can cancel super administrator approval")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="super administrator approval is not pending")
    approval.status = "cancelled"
    approval.decision_reason = body.reason
    uow.session.add(
        _audit(
            principal,
            request,
            "super_admin.approval_cancelled",
            approval.id,
            {"target_user_id": approval.target_user_id, "reason": body.reason},
            target_type="super_admin_approval",
        )
    )
    await uow.commit()
    return {"id": approval.id, "status": approval.status}


def _audit_log_view(row: AuditLogORM, actor_email: str | None) -> dict[str, object]:
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "actor_email": actor_email,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "request_id": row.request_id,
        "details": row.details,
        "created_at": row.created_at,
    }


@router.get("/audit-logs")
async def admin_audit_logs(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    action_prefix: Annotated[str, Query(max_length=80)] = "",
    actor_id: Annotated[str, Query(max_length=36)] = "",
    target_id: Annotated[str, Query(max_length=120)] = "",
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict[str, object]:
    """Search high-assurance operator actions without exposing player prose."""

    await set_tenant_context(uow.session, principal.user_id)
    prefix = action_prefix.strip()
    if prefix and not re.fullmatch(r"[a-z0-9_.-]+", prefix):
        raise HTTPException(status_code=422, detail="action_prefix has invalid characters")
    filters: list[Any] = []
    if prefix:
        filters.append(AuditLogORM.action.startswith(prefix, autoescape=True))
    if actor_id.strip():
        filters.append(AuditLogORM.actor_id == actor_id.strip())
    if target_id.strip():
        filters.append(AuditLogORM.target_id == target_id.strip())
    if before is not None:
        filters.append(AuditLogORM.created_at < before)
    rows = (
        await uow.session.execute(
            sa.select(AuditLogORM, UserORM.email)
            .outerjoin(UserORM, UserORM.id == AuditLogORM.actor_id)
            .where(*filters)
            .order_by(AuditLogORM.created_at.desc(), AuditLogORM.id.desc())
            .limit(limit + 1)
        )
    ).all()
    page = rows[:limit]
    next_before = page[-1][0].created_at if len(rows) > limit and page else None
    return {
        "items": [_audit_log_view(row, email) for row, email in page],
        "next_before": next_before,
        "limit": limit,
    }


@router.get("/audit-summary")
async def admin_audit_summary(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
) -> dict[str, object]:
    """Recent change pressure for the operations dashboard, with no PII."""

    await set_tenant_context(uow.session, principal.user_id)
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        await uow.session.execute(
            sa.select(AuditLogORM.action, sa.func.count())
            .where(AuditLogORM.created_at >= since)
            .group_by(AuditLogORM.action)
            .order_by(sa.func.count().desc(), AuditLogORM.action.asc())
            .limit(20)
        )
    ).all()
    return {
        "hours": hours,
        "actions": [{"action": str(action), "count": int(count)} for action, count in rows],
    }


# ---------------------------------------------------------------------------
# Population-wide controls
# ---------------------------------------------------------------------------
def _user_filter(scope: str, role: str | None, query: str) -> list[Any]:
    filters: list[Any] = []
    if scope == "search" and query.strip():
        needle = f"%{query.strip()}%"
        filters.append(sa.or_(UserORM.email.ilike(needle), UserORM.display_name.ilike(needle)))
    elif scope == "role" and role:
        filters.append(
            UserORM.id.in_(sa.select(UserRoleORM.user_id).where(UserRoleORM.role == role))
        )
    # Never touch the system content account: it owns the official releases and
    # has no human behind it to notice being suspended or re-quota'd.
    filters.append(UserORM.status != "system")
    return filters


def _audit(
    principal: Principal,
    request: Request,
    action: str,
    target_id: str,
    details: dict[str, Any],
    target_type: str = "user",
) -> AuditLogORM:
    return AuditLogORM(
        id=new_id(),
        actor_id=principal.user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        request_id=str(getattr(request.state, "request_id", "")),
        details=details,
    )


async def _revoke_sessions(uow: SqlUnitOfWork, user_id: str) -> int:
    result = await uow.session.execute(
        sa.update(AuthSessionORM)
        .where(AuthSessionORM.user_id == user_id, AuthSessionORM.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]  # DML result



async def _turn_numbers(uow: SqlUnitOfWork, session_ids: list[str | None]) -> dict[str, int]:
    """How far each playthrough has actually got, read from its game session."""
    wanted = [session_id for session_id in session_ids if session_id]
    if not wanted:
        return {}
    rows = (
        await uow.session.execute(
            sa.select(GameSessionORM.id, GameSessionORM.turn_number).where(
                GameSessionORM.id.in_(wanted)
            )
        )
    ).all()
    return {str(session_id): int(turn_number or 0) for session_id, turn_number in rows}

@router.get("/users/quota/bulk/preview")
async def preview_bulk_quota(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    scope: Annotated[Literal["all", "role", "search"], Query()] = "all",
    role: Annotated[str, Query(max_length=32)] = "",
    query: Annotated[str, Query(max_length=120)] = "",
) -> dict[str, object]:
    """How many accounts a bulk change would touch, and a sample of them."""
    await set_tenant_context(uow.session, principal.user_id)
    filters = _user_filter(scope, role or None, query)
    matched = int(
        await uow.session.scalar(sa.select(sa.func.count()).select_from(UserORM).where(*filters))
        or 0
    )
    sample = (
        (
            await uow.session.execute(
                sa.select(UserORM.email)
                .where(*filters)
                .order_by(UserORM.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    return {"matched": matched, "sample": list(sample)}


@router.post("/users/quota/bulk")
async def set_quota_in_bulk(
    body: BulkQuotaWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Apply one monthly quota to every account the filter selects."""
    await set_tenant_context(uow.session, principal.user_id)
    filters = _user_filter(body.scope, body.role, body.query)
    matched = int(
        await uow.session.scalar(sa.select(sa.func.count()).select_from(UserORM).where(*filters))
        or 0
    )
    if matched != body.expect_users:
        raise HTTPException(
            status_code=409,
            detail=(
                f"the filter now matches {matched} accounts, not {body.expect_users}; "
                "re-read the count and submit again"
            ),
        )
    await uow.session.execute(
        sa.update(UserORM).where(*filters).values(platform_quota_monthly=body.monthly_tokens)
    )
    uow.session.add(
        _audit(
            principal,
            request,
            "user.quota_bulk_changed",
            target_id="*",
            details={
                "scope": body.scope,
                "role": body.role,
                "query": body.query,
                "monthly_tokens": body.monthly_tokens,
                "affected": matched,
                "reason": body.reason,
            },
        )
    )
    await uow.commit()
    return {"affected": matched, "monthly_quota": body.monthly_tokens}


@router.get("/settings")
async def read_platform_settings(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    return {
        "default_quota": await read_setting(uow, DEFAULT_QUOTA_KEY, DEFAULT_QUOTA_FALLBACK),
        "announcement": await read_setting(uow, ANNOUNCEMENT_KEY, EMPTY_ANNOUNCEMENT),
    }


@router.put("/settings/default-quota")
async def set_default_quota(
    body: DefaultQuotaWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """The quota new accounts are created with. Existing accounts are untouched."""
    await set_tenant_context(uow.session, principal.user_id)
    await write_setting(
        uow, principal.user_id, DEFAULT_QUOTA_KEY, {"monthly_tokens": body.monthly_tokens}
    )
    uow.session.add(
        _audit(
            principal,
            request,
            "platform.default_quota_changed",
            DEFAULT_QUOTA_KEY,
            {"monthly_tokens": body.monthly_tokens, "reason": body.reason},
            target_type="platform",
        )
    )
    await uow.commit()
    return {"monthly_tokens": body.monthly_tokens}


@router.put("/settings/announcement")
async def set_announcement(
    body: AnnouncementWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """A banner every signed-in player sees, for maintenance and incidents."""
    await set_tenant_context(uow.session, principal.user_id)
    payload: dict[str, Any] = {
        "message": body.message.strip(),
        "level": body.level,
        "active": bool(body.active and body.message.strip()),
    }
    await write_setting(uow, principal.user_id, ANNOUNCEMENT_KEY, payload)
    uow.session.add(
        _audit(
            principal,
            request,
            "platform.announcement_changed",
            ANNOUNCEMENT_KEY,
            {**payload, "reason": body.reason},
            target_type="platform",
        )
    )
    await uow.commit()
    return payload


# ---------------------------------------------------------------------------
# Individual account controls
# ---------------------------------------------------------------------------
@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: str,
    body: SuspendWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Block or restore sign-in. Suspending also ends every live session."""
    await set_tenant_context(uow.session, principal.user_id)
    if user_id == principal.user_id:
        raise HTTPException(status_code=409, detail="administrator cannot suspend themselves")
    user = await _target_user(uow, user_id)
    if user.status == "system":
        raise HTTPException(status_code=409, detail="the system account cannot be suspended")
    before = user.status
    user.status = "suspended" if body.suspended else "active"
    if body.suspended:
        await _revoke_sessions(uow, user_id)
    uow.session.add(
        _audit(
            principal,
            request,
            "user.suspended" if body.suspended else "user.reinstated",
            user_id,
            {"before": before, "after": user.status, "reason": body.reason},
        )
    )
    await uow.commit()
    return {"user_id": user_id, "status": user.status}


@router.post("/users/{user_id}/revoke-sessions")
async def revoke_user_sessions(
    user_id: str,
    body: AccountActionWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Sign an account out everywhere, without blocking a fresh sign-in."""
    await set_tenant_context(uow.session, principal.user_id)
    await _target_user(uow, user_id)
    revoked = await _revoke_sessions(uow, user_id)
    uow.session.add(
        _audit(
            principal,
            request,
            "user.sessions_revoked",
            user_id,
            {"revoked": revoked, "reason": body.reason},
        )
    )
    await uow.commit()
    return {"user_id": user_id, "revoked": revoked}


@router.post("/users/{user_id}/verify-email")
async def force_verify_email(
    user_id: str,
    body: AccountActionWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Mark an address verified when delivery is the thing that is broken."""
    await set_tenant_context(uow.session, principal.user_id)
    user = await _target_user(uow, user_id)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
        uow.session.add(
            _audit(
                principal, request, "user.email_force_verified", user_id, {"reason": body.reason}
            )
        )
        await uow.commit()
    return {"user_id": user_id, "verified": True}


@router.post("/users/{user_id}/usage/reset")
async def reset_monthly_usage(
    user_id: str,
    body: AccountActionWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Forgive this month's platform spend without changing the quota.

    The ledger is append-only accounting, so nothing is deleted: a negative
    correction entry is written and the running total moves back to zero.
    """
    await set_tenant_context(uow.session, principal.user_id)
    await _target_user(uow, user_id)
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = int(
        await uow.session.scalar(
            sa.select(
                sa.func.coalesce(
                    sa.func.sum(UsageLedgerORM.input_tokens + UsageLedgerORM.output_tokens), 0
                )
            ).where(
                UsageLedgerORM.user_id == user_id,
                UsageLedgerORM.created_at >= month_start,
                UsageLedgerORM.provider != "byok",
            )
        )
        or 0
    )
    if spent > 0:
        uow.session.add(
            UsageLedgerORM(
                id=new_id(),
                user_id=user_id,
                provider="platform",
                model="admin-correction",
                input_tokens=-spent,
                output_tokens=0,
                success=True,
            )
        )
        uow.session.add(
            _audit(
                principal,
                request,
                "user.usage_reset",
                user_id,
                {"forgiven_tokens": spent, "reason": body.reason},
            )
        )
        await uow.commit()
    return {"user_id": user_id, "forgiven_tokens": spent}


@router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: str,
    body: DeleteUserWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Irreversibly erase an account. Not a row delete - see ``scrub_account``.

    Several tables reference ``users.id`` without a cascade, and published
    releases may already back other people's playthroughs, so a hard delete
    both fails and would be wrong. This runs the same scrub the scheduled
    deletion job runs: personal data goes, the row survives as a pseudonym.
    """
    await set_tenant_context(uow.session, principal.user_id)
    if user_id == principal.user_id:
        raise HTTPException(status_code=409, detail="administrator cannot delete themselves")
    user = await _target_user(uow, user_id)
    if user.status == "system":
        raise HTTPException(status_code=409, detail="the system account cannot be deleted")
    if body.confirm_email.strip().casefold() != user.email:
        raise HTTPException(status_code=409, detail="confirmation address does not match")
    # Recorded before the address is overwritten - the audit trail has to
    # outlive the account it describes.
    uow.session.add(
        _audit(
            principal, request, "user.deleted", user_id,
            {"email": user.email, "reason": body.reason},
        )
    )
    await scrub_account(uow.session, user, reason=body.reason)
    await uow.commit()
    return {"user_id": user_id, "deleted": True}


@router.post("/releases/{release_id}/takedown")
async def force_takedown(
    release_id: str,
    body: TakedownWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Pull a published work off the platform immediately, or put it back."""
    await set_tenant_context(uow.session, principal.user_id)
    release = await uow.session.get(ContentReleaseORM, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    before = release.moderation_status
    release.moderation_status = "approved" if body.restore else "taken_down"
    if not body.restore:
        release.visibility = "private"
    uow.session.add(
        _audit(
            principal,
            request,
            "release.restored" if body.restore else "release.taken_down",
            release_id,
            {"before": before, "after": release.moderation_status, "reason": body.reason},
            target_type="release",
        )
    )
    await uow.commit()
    return {"release_id": release_id, "moderation_status": release.moderation_status}


@router.post("/users/{user_id}/inspect")
async def inspect_player(
    user_id: str,
    body: AccountActionWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Look at a player's game the way they see it - read-only, and on the record.

    Support questions about a stuck or broken playthrough cannot be answered
    from aggregate metrics; someone has to see the actual story. That is real
    access to someone's private writing, so it is deliberately not a session
    switch: there is nothing here that can act as the player, take a turn, or
    change a single row.

    Three things keep it honest. It is a POST with a required reason, so it
    cannot be reached by wandering around the interface. Administrator MFA
    step-up already gates every admin write. And every call writes an audit
    entry the player can read on their own account page - being able to find
    out that someone looked is the part that makes the power acceptable.
    """
    await set_tenant_context(uow.session, principal.user_id)
    user = await _target_user(uow, user_id)
    plays = (
        (
            await uow.session.execute(
                sa.select(PlaythroughORM)
                .where(PlaythroughORM.user_id == user_id)
                .order_by(PlaythroughORM.updated_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    turn_numbers = await _turn_numbers(uow, [play.game_session_id for play in plays])
    uow.session.add(
        _audit(
            principal,
            request,
            "user.inspected",
            user_id,
            {"reason": body.reason, "playthroughs": len(plays)},
        )
    )
    await uow.commit()
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "status": user.status,
            "verified": user.email_verified_at is not None,
            "monthly_quota": user.platform_quota_monthly,
        },
        "playthroughs": [
            {
                "id": play.id,
                "release_id": play.release_id,
                "status": play.status,
                "turn_number": turn_numbers.get(play.game_session_id or "", 0),
                "updated_at": play.updated_at,
            }
            for play in plays
        ],
        "read_only": True,
    }


@router.post("/users/{user_id}/inspect/{playthrough_id}")
async def inspect_playthrough(
    user_id: str,
    playthrough_id: str,
    body: AccountActionWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    limit: Annotated[int, Query(ge=1, le=40)] = 12,
) -> dict[str, object]:
    """Read a story excerpt only with MFA, an explicit reason and an audit row."""
    await set_tenant_context(uow.session, principal.user_id)
    play = await uow.session.get(PlaythroughORM, playthrough_id)
    if play is None or play.user_id != user_id:
        raise HTTPException(status_code=404, detail="playthrough not found")
    segments = await uow.turns.list_narrative(play.game_session_id or "", limit=limit)
    turn_numbers = await _turn_numbers(uow, [play.game_session_id])
    uow.session.add(
        _audit(
            principal,
            request,
            "user.playthrough_inspected",
            user_id,
            {
                "reason": body.reason,
                "playthrough_id": play.id,
                "segment_count": len(segments),
                "limit": limit,
            },
        )
    )
    await uow.commit()
    return {
        "playthrough_id": play.id,
        "status": play.status,
        "turn_number": turn_numbers.get(play.game_session_id or "", 0),
        "chapters": [
            {"kind": segment.kind, "text": segment.text, "world_minute": segment.world_minute}
            for segment in segments
            if segment.kind in {"chapter", "scene", "ending"}
        ],
        "read_only": True,
    }


@router.get("/system")
async def system_summary(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    token_sum = sa.func.coalesce(
        sa.func.sum(UsageLedgerORM.input_tokens + UsageLedgerORM.output_tokens), 0
    )
    users = int(await uow.session.scalar(sa.select(sa.func.count()).select_from(UserORM)) or 0)
    releases = int(
        await uow.session.scalar(sa.select(sa.func.count()).select_from(ContentReleaseORM)) or 0
    )
    pending = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(ModerationCaseORM)
            .where(ModerationCaseORM.status == "pending")
        )
        or 0
    )
    tokens = int(await uow.session.scalar(sa.select(token_sum)) or 0)
    failures = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(UsageLedgerORM)
            .where(UsageLedgerORM.success.is_(False))
        )
        or 0
    )
    recent_usage = (
        await uow.session.execute(
            sa.select(
                sa.func.count(),
                sa.func.coalesce(sa.func.sum(UsageLedgerORM.input_tokens + UsageLedgerORM.output_tokens), 0),
                sa.func.coalesce(sa.func.sum(UsageLedgerORM.cost_microunits), 0),
                sa.func.coalesce(
                    sa.func.sum(sa.case((UsageLedgerORM.success.is_(False), 1), else_=0)), 0
                ),
            ).where(UsageLedgerORM.created_at >= since)
        )
    ).one()
    recent_calls = int(recent_usage[0] or 0)
    recent_failures = int(recent_usage[3] or 0)
    active_sessions = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(AuthSessionORM)
            .where(AuthSessionORM.revoked_at.is_(None), AuthSessionORM.expires_at > now)
        )
        or 0
    )
    security_events = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLogORM)
            .where(
                AuditLogORM.created_at >= since,
                AuditLogORM.action.in_(
                    (
                        "auth.login_failed",
                        "auth.login_anomaly",
                        "auth.password_reset_requested",
                        "auth.password_reset_completed",
                        "auth.password_changed",
                        "auth.mfa_disabled",
                    )
                ),
            )
        )
        or 0
    )
    support_open_cases = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(SupportCaseORM)
            .where(SupportCaseORM.status.in_(("open", "in_progress", "waiting_user")))
        )
        or 0
    )
    support_unassigned_cases = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(SupportCaseORM)
            .where(
                SupportCaseORM.status.in_(("open", "in_progress", "waiting_user")),
                SupportCaseORM.assigned_to.is_(None),
            )
        )
        or 0
    )
    provider_rows = (
        await uow.session.execute(
            sa.select(
                UsageLedgerORM.provider,
                sa.func.count(),
                sa.func.coalesce(sa.func.sum(UsageLedgerORM.input_tokens + UsageLedgerORM.output_tokens), 0),
                sa.func.coalesce(sa.func.sum(UsageLedgerORM.cost_microunits), 0),
                sa.func.coalesce(
                    sa.func.sum(sa.case((UsageLedgerORM.success.is_(False), 1), else_=0)), 0
                ),
            )
            .where(UsageLedgerORM.created_at >= since)
            .group_by(UsageLedgerORM.provider)
            .order_by(sa.func.sum(UsageLedgerORM.cost_microunits).desc(), UsageLedgerORM.provider.asc())
            .limit(12)
        )
    ).all()
    return {
        "users": users,
        "releases": releases,
        "pending_moderation": pending,
        "llm_tokens": tokens,
        "llm_failures": failures,
        "operations_window_hours": 24,
        "llm_calls_24h": recent_calls,
        "llm_failures_24h": recent_failures,
        "llm_failure_rate_24h": round(recent_failures / recent_calls, 4) if recent_calls else 0.0,
        "llm_tokens_24h": int(recent_usage[1] or 0),
        "llm_cost_microunits_24h": int(recent_usage[2] or 0),
        "active_sessions": active_sessions,
        "security_events_24h": security_events,
        "support_open_cases": support_open_cases,
        "support_unassigned_cases": support_unassigned_cases,
        "model_usage_24h": [
            {
                "provider": str(provider or "unknown"),
                "calls": int(calls or 0),
                "tokens": int(row_tokens or 0),
                "cost_microunits": int(cost or 0),
                "failures": int(row_failures or 0),
            }
            for provider, calls, row_tokens, cost, row_failures in provider_rows
        ],
    }


@router.get("/operations-alerts")
async def operations_alerts(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Compute actionable, privacy-safe operational signals from durable state.

    The dashboard deliberately does not persist or acknowledge these alerts.
    They are a current view of database facts, so an operator cannot hide an
    unresolved financial, security or player-support risk by clicking away a
    notification.  Pager delivery remains the responsibility of Prometheus/
    Sentry deployment integrations; this endpoint is the audited human
    operations counterpart.
    """

    await set_tenant_context(uow.session, principal.user_id)
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    alerts: list[dict[str, object]] = []

    usage = (
        await uow.session.execute(
            sa.select(
                sa.func.count(),
                sa.func.coalesce(
                    sa.func.sum(sa.case((UsageLedgerORM.success.is_(False), 1), else_=0)), 0
                ),
            ).where(UsageLedgerORM.created_at >= since)
        )
    ).one()
    calls, failures = int(usage[0] or 0), int(usage[1] or 0)
    failure_rate = failures / calls if calls else 0.0
    if calls >= 5 and failure_rate >= 0.2:
        alerts.append(
            {
                "code": "llm_failure_rate_critical",
                "severity": "critical",
                "title": "模型调用失败率过高",
                "description": f"过去 24 小时 {failures}/{calls} 次模型调用失败（{failure_rate:.1%}）。",
                "value": failures,
                "href": "#operations-health",
            }
        )
    elif calls >= 5 and failure_rate >= 0.03:
        alerts.append(
            {
                "code": "llm_failure_rate_warning",
                "severity": "warning",
                "title": "模型调用失败率需要关注",
                "description": f"过去 24 小时 {failures}/{calls} 次模型调用失败（{failure_rate:.1%}）。",
                "value": failures,
                "href": "#operations-health",
            }
        )

    expired_holds = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(WalletHoldORM)
            .where(WalletHoldORM.status == "held", WalletHoldORM.expires_at < now)
        )
        or 0
    )
    if expired_holds:
        alerts.append(
            {
                "code": "expired_wallet_holds",
                "severity": "warning",
                "title": "发现过期的回合预授权",
                "description": f"有 {expired_holds} 笔预授权仍为 held 状态，应检查结算恢复与 worker 清理。",
                "value": expired_holds,
                "href": "#commerce-operations",
            }
        )

    open_case_statuses = ("open", "in_progress", "waiting_user")
    urgent_unassigned = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(SupportCaseORM)
            .where(
                SupportCaseORM.status.in_(open_case_statuses),
                SupportCaseORM.priority == "urgent",
                SupportCaseORM.assigned_to.is_(None),
            )
        )
        or 0
    )
    if urgent_unassigned:
        alerts.append(
            {
                "code": "urgent_support_unassigned",
                "severity": "critical",
                "title": "存在未分派的紧急支持请求",
                "description": f"有 {urgent_unassigned} 项紧急请求尚未明确负责人。",
                "value": urgent_unassigned,
                "href": "#support-operations",
            }
        )

    stale_support = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(SupportCaseORM)
            .where(
                SupportCaseORM.status.in_(open_case_statuses),
                SupportCaseORM.created_at < now - timedelta(hours=24),
            )
        )
        or 0
    )
    if stale_support:
        alerts.append(
            {
                "code": "support_response_sla_risk",
                "severity": "warning",
                "title": "支持请求可能超过首响目标",
                "description": f"有 {stale_support} 项未结束请求已创建超过 24 小时。",
                "value": stale_support,
                "href": "#support-operations",
            }
        )

    login_anomalies = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLogORM)
            .where(
                AuditLogORM.created_at >= since,
                AuditLogORM.action == "auth.login_anomaly",
            )
        )
        or 0
    )
    if login_anomalies >= 3:
        alerts.append(
            {
                "code": "login_anomaly_cluster",
                "severity": "warning",
                "title": "异常登录信号集中出现",
                "description": f"过去 24 小时记录了 {login_anomalies} 次异常登录信号，请核查安全事件与会话。",
                "value": login_anomalies,
                "href": "#audit-operations",
            }
        )

    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda row: (severity_rank[str(row["severity"])], str(row["code"])))
    return {
        "generated_at": now.isoformat(),
        "window_hours": 24,
        "healthy": not alerts,
        "counts": {
            "critical": sum(1 for row in alerts if row["severity"] == "critical"),
            "warning": sum(1 for row in alerts if row["severity"] == "warning"),
        },
        "alerts": alerts,
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
            sa.select(sa.func.count())
            .select_from(UserORM)
            .where(UserORM.analytics_consent.is_(True))
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
            "playthrough_started",
            "first_action",
            "third_turn",
            "ending_selected",
            "project_created",
            "project_validated",
            "release_created",
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
        _funnel_stage(
            "playthrough_started",
            "开始正式游戏",
            stage_users["playthrough_started"],
            stage_events["playthrough_started"],
        ),
        _funnel_stage(
            "first_action",
            "完成第一回合",
            stage_users["first_action"],
            stage_events["first_action"],
        ),
        _funnel_stage(
            "third_turn", "完成第三回合", stage_users["third_turn"], stage_events["third_turn"]
        ),
        _funnel_stage(
            "ending_selected",
            "抵达结局",
            stage_users["ending_selected"],
            stage_events["ending_selected"],
        ),
    ]
    creator = [
        _funnel_stage(
            "project_created",
            "创建项目",
            stage_users["project_created"],
            stage_events["project_created"],
        ),
        _funnel_stage(
            "project_validated",
            "通过校验",
            stage_users["project_validated"],
            stage_events["project_validated"],
        ),
        _funnel_stage(
            "release_created",
            "创建版本",
            stage_users["release_created"],
            stage_events["release_created"],
        ),
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

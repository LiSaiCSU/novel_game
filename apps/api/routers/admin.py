"""Administrator-only account, quota and operational controls."""

from __future__ import annotations

import json
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
from apps.api.rate_limit import rate_limiter
from apps.api.security import Principal, SecretBox, require_role_csrf, require_roles
from apps.api.tenancy import set_tenant_context
from database.models.platform import (
    AuditLogORM,
    ContentReleaseORM,
    ModerationCaseORM,
    PlatformLlmConfigORM,
    ProductEventORM,
    UsageLedgerORM,
    UserORM,
    UserRoleORM,
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
_ALLOWED_ROLES = frozenset({"player", "creator", "reviewer", "admin"})
logger = get_logger("admin")


def _funnel_stage(key: str, label: str, users: set[str], events: int) -> dict[str, object]:
    return {"key": key, "label": label, "unique_users": len(users), "events": events}


class QuotaWrite(BaseModel):
    monthly_tokens: int = Field(ge=0, le=100_000_000)
    reason: str = Field(min_length=3, max_length=500)


class RolesWrite(BaseModel):
    roles: set[Literal["player", "creator", "reviewer", "admin"]]
    reason: str = Field(min_length=3, max_length=500)


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
        )
        .scalars()
        .all()
    )
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

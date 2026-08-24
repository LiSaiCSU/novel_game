"""Private model credentials, data portability and account lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Annotated, Literal
from urllib.parse import urlsplit

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator

from apps.api.deps import settings_dep, uow_dep
from apps.api.object_store import object_store
from apps.api.rate_limit import rate_limiter
from apps.api.security import Principal, SecretBox, require_csrf, verified_principal
from apps.api.tenancy import set_tenant_context
from apps.jobs import enqueue_job
from database.models.platform import (
    AuditLogORM,
    AuthSessionORM,
    ContentReleaseORM,
    DataExportORM,
    LlmCredentialORM,
    PlaythroughORM,
    ProductEventORM,
    ProjectORM,
    SupportCaseORM,
    UsageLedgerORM,
    UserORM,
)
from database.repositories.sql import SqlUnitOfWork
from engine.core.config import Settings
from engine.core.ids import new_id
from engine.llm.provider import LLMMessage, LLMRequest
from engine.llm.providers import build_provider

router = APIRouter(prefix="/settings", tags=["v1-settings"])


class CredentialWrite(BaseModel):
    provider: Literal["openai", "anthropic", "compatible"]
    model: str = Field(min_length=1, max_length=160)
    secret: str = Field(min_length=8, max_length=1000)
    base_url: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_endpoint(self) -> CredentialWrite:
        self.model = self.model.strip()
        self.base_url = self.base_url.strip().rstrip("/")
        if self.provider == "compatible" and not self.base_url:
            raise ValueError("OpenAI-compatible providers require an API base URL")
        if not self.base_url:
            return self
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("API base URL must be a public HTTPS URL without credentials")
        hostname = parsed.hostname.casefold().rstrip(".")
        if hostname == "localhost" or hostname.endswith(".local"):
            raise ValueError("API base URL must not target a local service")
        try:
            address = ip_address(hostname)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError("API base URL must not target a private network")
        return self


class PrivacyPreferencesWrite(BaseModel):
    product_analytics: bool


def _privacy_view(user: UserORM) -> dict[str, object]:
    return {
        "product_analytics": user.analytics_consent,
        "consent_updated_at": user.analytics_consent_updated_at,
        "collection": {
            "events": "仅收集服务器定义的开始游戏、完成回合、结局与创作流程事件",
            "never": ["玩家输入", "生成正文", "邮箱", "模型密钥", "IP 地址"],
            "retention": "关闭后立即删除既有产品分析事件",
        },
    }


def _secret_box(settings: Settings) -> SecretBox:
    try:
        return SecretBox(settings.credential_encryption_key)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="BYOK encryption is not configured") from exc


@router.get("/privacy")
async def privacy_preferences(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    user = await uow.session.get(UserORM, principal.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="account not found")
    return _privacy_view(user)


@router.get("/privacy/access-log")
async def administrator_access_log(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    """Every time an administrator opened this account's private content.

    Support sometimes has to read a player's writing to answer a question
    about it. Whether that is acceptable rests on the player being able to
    find out it happened, so the record is theirs to read, not only ours.
    """
    await set_tenant_context(uow.session, principal.user_id)
    own_support_case_ids = sa.select(SupportCaseORM.id).where(
        SupportCaseORM.user_id == principal.user_id
    )
    rows = (
        (
            await uow.session.execute(
                sa.select(AuditLogORM)
                .where(
                    sa.or_(
                        sa.and_(
                            AuditLogORM.target_type == "user",
                            AuditLogORM.target_id == principal.user_id,
                            AuditLogORM.action.in_(("user.inspected", "user.playthrough_inspected")),
                        ),
                        sa.and_(
                            AuditLogORM.target_type == "support_case",
                            AuditLogORM.target_id.in_(own_support_case_ids),
                            AuditLogORM.action == "support.case_inspected",
                        ),
                    )
                )
                .order_by(AuditLogORM.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return {
        "entries": [
            {
                "at": row.created_at,
                "reason": str((row.details or {}).get("reason", "")),
            }
            for row in rows
        ]
    }


@router.put("/privacy")
async def update_privacy_preferences(
    body: PrivacyPreferencesWrite,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    user = await uow.session.get(UserORM, principal.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="account not found")
    changed = user.analytics_consent != body.product_analytics
    if not body.product_analytics:
        await uow.session.execute(
            sa.delete(ProductEventORM).where(ProductEventORM.user_id == principal.user_id)
        )
    user.analytics_consent = body.product_analytics
    if changed or user.analytics_consent_updated_at is None:
        user.analytics_consent_updated_at = datetime.now(UTC)
    if changed and body.product_analytics:
        uow.session.add(
            ProductEventORM(
                id=new_id(),
                user_id=principal.user_id,
                event_name="analytics_opted_in",
                event_properties={},
            )
        )
    await uow.commit()
    return _privacy_view(user)


@router.get("/llm-credentials")
async def list_credentials(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> list[dict[str, str]]:
    await set_tenant_context(uow.session, principal.user_id)
    rows = (
        await uow.session.execute(
            sa.select(LlmCredentialORM).where(LlmCredentialORM.user_id == principal.user_id)
        )
    ).scalars().all()
    return [
        {"provider": row.provider, "model": row.default_model, "hint": row.key_hint,
         "status": row.status, "base_url": row.base_url}
        for row in rows
    ]


@router.get("/llm-usage")
async def llm_usage(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    token_sum = sa.func.coalesce(
        sa.func.sum(UsageLedgerORM.input_tokens + UsageLedgerORM.output_tokens), 0
    )
    async def used_since(since: datetime) -> int:
        return int(await uow.session.scalar(sa.select(token_sum).where(
            UsageLedgerORM.user_id == principal.user_id,
            UsageLedgerORM.created_at >= since,
            UsageLedgerORM.provider != "byok",
        )) or 0)
    user = await uow.session.get(UserORM, principal.user_id)
    monthly_limit = min(
        settings.llm_monthly_token_limit,
        user.platform_quota_monthly if user else settings.llm_monthly_token_limit,
    )
    daily, monthly = await used_since(day_start), await used_since(month_start)
    return {
        "daily": {"used": daily, "limit": settings.llm_daily_token_limit},
        "monthly": {"used": monthly, "limit": monthly_limit},
        "turn_limit": settings.llm_turn_token_limit,
    }


@router.put("/llm-credentials")
async def save_credential(
    body: CredentialWrite,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, str]:
    await set_tenant_context(uow.session, principal.user_id)
    row = await uow.session.scalar(
        sa.select(LlmCredentialORM).where(
            LlmCredentialORM.user_id == principal.user_id,
            LlmCredentialORM.provider == body.provider,
        )
    )
    encrypted = _secret_box(settings).encrypt(body.secret)
    hint = f"…{body.secret[-4:]}"
    if row is None:
        row = LlmCredentialORM(
            id=new_id(), user_id=principal.user_id, provider=body.provider,
            default_model=body.model, base_url=body.base_url, encrypted_secret=encrypted,
            key_hint=hint, status="active",
        )
        uow.session.add(row)
    else:
        row.encrypted_secret = encrypted
        row.default_model = body.model
        row.base_url = body.base_url
        row.key_hint = hint
        row.status = "active"
    await uow.commit()
    return {"provider": row.provider, "model": row.default_model, "hint": row.key_hint,
            "status": row.status, "base_url": row.base_url}


@router.delete("/llm-credentials/{provider}", status_code=204)
async def delete_credential(
    provider: str,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> Response:
    await set_tenant_context(uow.session, principal.user_id)
    await uow.session.execute(
        sa.delete(LlmCredentialORM).where(
            LlmCredentialORM.user_id == principal.user_id,
            LlmCredentialORM.provider == provider,
        )
    )
    await uow.commit()
    return Response(status_code=204)


@router.post("/llm-credentials/{provider}/test")
async def test_credential(
    provider: str,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    await rate_limiter.check(
        f"credential-test:{principal.user_id}", 3, 60, redis_url=settings.redis_url
    )
    row = await uow.session.scalar(
        sa.select(LlmCredentialORM).where(
            LlmCredentialORM.user_id == principal.user_id,
            LlmCredentialORM.provider == provider,
            LlmCredentialORM.status == "active",
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="credential not found")
    try:
        secret = _secret_box(settings).decrypt(row.encrypted_secret)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="credential cannot be decrypted") from exc
    runtime_settings = settings.model_copy(
        update={
            "llm_provider": row.provider,
            "llm_api_key": secret,
            "llm_api_keys": "",
            "llm_base_url": row.base_url,
            "llm_model": row.default_model,
            "llm_timeout_seconds": min(settings.llm_timeout_seconds, 15),
        }
    )
    client = build_provider(runtime_settings)
    try:
        result = await client.generate_text(
            LLMRequest(
                model=row.default_model,
                messages=[LLMMessage(content="Reply with OK.")],
                temperature=0,
                max_output_tokens=8,
            )
        )
    except Exception as exc:
        uow.session.add(
            UsageLedgerORM(
                id=new_id(), user_id=principal.user_id, provider="byok",
                model=row.default_model, input_tokens=0, output_tokens=0,
                cost_microunits=0, success=False,
            )
        )
        await uow.commit()
        raise HTTPException(status_code=502, detail="credential test failed") from exc
    uow.session.add(
        UsageLedgerORM(
            id=new_id(), user_id=principal.user_id, provider="byok",
            model=result.model or row.default_model,
            input_tokens=result.usage.prompt_tokens,
            output_tokens=result.usage.completion_tokens,
            cost_microunits=0, success=True,
        )
    )
    await uow.commit()
    return {"status": "ok", "provider": row.provider, "model": result.model or row.default_model,
            "latency_ms": result.latency_ms}


@router.get("/data-export")
async def export_personal_data(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    user = await uow.session.get(UserORM, principal.user_id)
    projects = (await uow.session.execute(sa.select(ProjectORM).where(ProjectORM.owner_id == principal.user_id))).scalars().all()
    releases = (await uow.session.execute(sa.select(ContentReleaseORM).where(ContentReleaseORM.owner_id == principal.user_id))).scalars().all()
    plays = (await uow.session.execute(sa.select(PlaythroughORM).where(PlaythroughORM.user_id == principal.user_id))).scalars().all()
    return {
        "exported_at": datetime.now(UTC),
        "account": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "locale": user.locale,
            "product_analytics": user.analytics_consent,
            "analytics_consent_updated_at": user.analytics_consent_updated_at,
        } if user else None,
        "projects": [{"id": row.id, "slug": row.slug, "title": row.title, "revision": row.current_revision} for row in projects],
        "releases": [{"id": row.id, "version": row.version, "checksum": row.checksum} for row in releases],
        "playthroughs": [{"id": row.id, "release_id": row.release_id, "name": row.name, "status": row.status} for row in plays],
    }


def _export_view(row: DataExportORM) -> dict[str, object]:
    return {
        "id": row.id,
        "status": row.status,
        "byte_size": row.byte_size,
        "error_code": row.error_code,
        "expires_at": row.expires_at,
        "download_url": f"/api/v1/settings/data-exports/{row.id}/download"
        if row.status == "ready" and row.object_key else None,
    }


@router.post("/data-exports", status_code=202)
async def request_personal_data_export(
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    recent = await uow.session.scalar(
        sa.select(DataExportORM).where(
            DataExportORM.user_id == principal.user_id,
            DataExportORM.status.in_(("queued", "processing")),
        ).order_by(DataExportORM.created_at.desc())
    )
    if recent is not None:
        return _export_view(recent)
    row = DataExportORM(
        id=new_id(), user_id=principal.user_id, status="queued",
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    uow.session.add(row)
    await uow.commit()
    queued = await enqueue_job(
        settings, "build_data_export", {"export_id": row.id, "user_id": principal.user_id}
    )
    if not queued:
        from apps.worker.tasks import build_data_export

        await build_data_export(settings, row.id, principal.user_id)
        await uow.session.refresh(row)
    return _export_view(row)


@router.get("/data-exports/{export_id}")
async def personal_data_export_status(
    export_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    row = await uow.session.scalar(
        sa.select(DataExportORM).where(
            DataExportORM.id == export_id, DataExportORM.user_id == principal.user_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="data export not found")
    return _export_view(row)


@router.get("/data-exports/{export_id}/download")
async def download_personal_data_export(
    export_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> Response:
    await set_tenant_context(uow.session, principal.user_id)
    row = await uow.session.scalar(
        sa.select(DataExportORM).where(
            DataExportORM.id == export_id, DataExportORM.user_id == principal.user_id
        )
    )
    expires_at = row.expires_at if row else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if (
        row is None or row.status != "ready" or not row.object_key
        or expires_at is None or expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(status_code=404, detail="data export is unavailable")
    try:
        payload = await object_store(settings).get(row.object_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="data export is unavailable") from exc
    return Response(
        payload,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="narrative-export-{row.id}.json"',
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/account", status_code=202)
async def schedule_account_deletion(
    response: Response,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    user = await uow.session.get(UserORM, principal.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="account not found")
    user.status = "deletion_pending"
    user.delete_after = datetime.now(UTC) + timedelta(days=30)
    await uow.session.execute(
        sa.update(AuthSessionORM)
        .where(AuthSessionORM.user_id == principal.user_id, AuthSessionORM.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await uow.commit()
    response.delete_cookie(settings.auth_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return {"status": user.status, "delete_after": user.delete_after}

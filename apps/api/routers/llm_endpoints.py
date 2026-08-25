"""Administrator management of the platform's model endpoint chain.

The platform used to hold exactly one model connection, so a bad key, a
retired model name or a gateway outage stopped every turn on the site and the
only recovery was an operator editing one row under pressure. This router
manages an ordered list instead: several independent endpoints, tried in
priority order, each with its own credential and its own model names.

The preflight here deliberately does more work than a ping. The old connection
test asked for ninety-six tokens of ``{"status":"ok"}`` over a non-streaming
request, which a gateway can satisfy while still failing every real turn — the
visible prose is streamed, and the reasoning stages demand schema-shaped JSON
at a far larger budget. A test that cannot fail the way play fails is worse
than no test, because it converts a broken configuration into a confident one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from apps.api.deps import settings_dep, uow_dep
from apps.api.llm_config import (
    SUPPORTED_PLATFORM_PROVIDERS,
    endpoint_view,
    load_platform_endpoints,
    normalize_public_api_base_url,
)
from apps.api.rate_limit import rate_limiter
from apps.api.security import Principal, SecretBox, require_role_csrf, require_roles
from apps.api.tenancy import set_tenant_context
from database.models.platform import AuditLogORM, PlatformLlmEndpointORM
from database.repositories.sql import SqlUnitOfWork
from engine.core.config import Settings
from engine.core.ids import new_id
from engine.core.logging import get_logger
from engine.llm.provider import LLMMessage, LLMRequest
from engine.llm.providers import _http_provider, _split_api_keys

router = APIRouter(prefix="/admin/llm-endpoints", tags=["v1-admin"])
logger = get_logger("aiworld.admin.llm")

#: Long enough that a context or output-budget limit shows up, small enough
#: that a healthy endpoint answers within the operator's patience.
_PREFLIGHT_NARRATIVE_TOKENS = 700
_PREFLIGHT_REASONING_TOKENS = 900
_MAX_ENDPOINTS = 8


class EndpointWrite(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=999)
    provider: str = Field(default="compatible", max_length=60)
    base_url: str = Field(default="", max_length=500)
    narrative_model: str = Field(default="", max_length=160)
    reasoning_model: str = Field(default="", max_length=160)
    narrative_extra_body: dict[str, Any] = Field(default_factory=dict)
    reasoning_extra_body: dict[str, Any] = Field(default_factory=dict)
    #: ``None`` keeps the stored credential; a string replaces it.
    api_key: str | None = None


def _audit(
    request: Request, principal: Principal, action: str, target: str, details: dict[str, Any]
) -> AuditLogORM:
    return AuditLogORM(
        id=new_id(),
        actor_id=principal.user_id,
        action=action,
        target_type="platform_llm_endpoint",
        target_id=target,
        request_id=str(getattr(request.state, "request_id", "")),
        details=details,
    )


def _apply(row: PlatformLlmEndpointORM, body: EndpointWrite, settings: Settings) -> None:
    if body.provider not in SUPPORTED_PLATFORM_PROVIDERS:
        raise HTTPException(status_code=422, detail="unsupported platform model provider")
    try:
        base_url = normalize_public_api_base_url(
            body.base_url, required=body.provider == "compatible"
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not body.narrative_model.strip():
        raise HTTPException(status_code=422, detail="叙事模型名称不能为空")
    row.name = body.name.strip()
    row.enabled = body.enabled
    row.priority = body.priority
    row.provider = body.provider
    row.base_url = base_url
    row.narrative_model = body.narrative_model.strip()
    row.reasoning_model = body.reasoning_model.strip() or body.narrative_model.strip()
    row.narrative_extra_body = dict(body.narrative_extra_body or {})
    row.reasoning_extra_body = dict(body.reasoning_extra_body or {})
    if body.api_key is not None:
        try:
            row.encrypted_secret = SecretBox(settings.credential_encryption_key).encrypt(
                body.api_key
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=503, detail="platform credential encryption is not configured"
            ) from exc
        row.key_hint = f"…{body.api_key[-4:]}" if len(body.api_key) >= 4 else "…"


@router.get("")
async def list_endpoints(
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    rows = await load_platform_endpoints(uow.session)
    return {
        "items": [endpoint_view(row) for row in rows],
        "supported_providers": sorted(SUPPORTED_PLATFORM_PROVIDERS),
        "max_endpoints": _MAX_ENDPOINTS,
    }


@router.post("", status_code=201)
async def create_endpoint(
    body: EndpointWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    existing = await load_platform_endpoints(uow.session)
    if len(existing) >= _MAX_ENDPOINTS:
        raise HTTPException(
            status_code=409, detail=f"最多只能配置 {_MAX_ENDPOINTS} 个端点"
        )
    row = PlatformLlmEndpointORM(id=new_id())
    _apply(row, body, settings)
    uow.session.add(row)
    await uow.session.flush()
    uow.session.add(
        _audit(
            request,
            principal,
            "platform_llm_endpoint.created",
            row.id,
            {"name": row.name, "provider": row.provider, "priority": row.priority},
        )
    )
    await uow.commit()
    return endpoint_view(row)


@router.put("/{endpoint_id}")
async def update_endpoint(
    endpoint_id: str,
    body: EndpointWrite,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    row = await uow.session.get(PlatformLlmEndpointORM, endpoint_id)
    if row is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    before = endpoint_view(row)
    _apply(row, body, settings)
    row.updated_by = principal.user_id
    await uow.session.flush()
    uow.session.add(
        _audit(
            request,
            principal,
            "platform_llm_endpoint.updated",
            row.id,
            {
                "before": {k: before[k] for k in ("name", "provider", "enabled", "priority")},
                "after": {
                    "name": row.name,
                    "provider": row.provider,
                    "enabled": row.enabled,
                    "priority": row.priority,
                },
                "key_rotated": body.api_key is not None,
            },
        )
    )
    await uow.commit()
    return endpoint_view(row)


@router.delete("/{endpoint_id}", status_code=204)
async def delete_endpoint(
    endpoint_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> None:
    await set_tenant_context(uow.session, principal.user_id)
    row = await uow.session.get(PlatformLlmEndpointORM, endpoint_id)
    if row is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    remaining = [
        item
        for item in await load_platform_endpoints(uow.session)
        if item.id != endpoint_id and item.enabled
    ]
    if row.enabled and not remaining:
        # Removing the only way to reach a model takes the whole site down, so
        # make it a deliberate two-step: disable it, or add a replacement first.
        raise HTTPException(
            status_code=409, detail="这是最后一个可用端点，删除后平台将无法生成内容"
        )
    uow.session.add(
        _audit(
            request, principal, "platform_llm_endpoint.deleted", row.id, {"name": row.name}
        )
    )
    await uow.session.delete(row)
    await uow.commit()


async def _probe(
    row: PlatformLlmEndpointORM, settings: Settings, stage: Literal["narrative", "reasoning"]
) -> dict[str, object]:
    """Exercise one endpoint the way the turn loop will actually use it."""

    keys = _split_api_keys("")
    if row.encrypted_secret:
        try:
            keys = [SecretBox(settings.credential_encryption_key).decrypt(row.encrypted_secret)]
        except ValueError:
            return {"stage": stage, "ok": False, "detail": "凭证无法解密，请重新填写密钥"}
    if not keys:
        keys = [""]
    model = row.narrative_model if stage == "narrative" else (
        row.reasoning_model or row.narrative_model
    )
    if not model.strip():
        return {"stage": stage, "ok": False, "detail": "模型名称未配置"}

    provider = _http_provider(row.provider, keys[0], row.base_url, float(settings.llm_timeout_seconds))
    extra = dict(
        row.narrative_extra_body if stage == "narrative" else row.reasoning_extra_body
    )
    started = datetime.now(UTC)
    try:
        if stage == "narrative":
            # Stream a realistic scene length. A gateway that answers a short
            # non-streaming ping but stalls on SSE fails exactly here, which is
            # the failure the old test could never see.
            request = LLMRequest(
                model=model,
                system="你是一个中文小说叙述者。只输出正文，不要解释。",
                messages=[LLMMessage(content="用第二人称写一段约四百字的场景描写，主题是雨夜的车站。")],
                temperature=0.7,
                max_output_tokens=_PREFLIGHT_NARRATIVE_TOKENS,
                extra_body=extra,
                role="narrative",
            )
            chunks: list[str] = []
            async for chunk in provider.stream_text(request):
                chunks.append(chunk)
            text = "".join(chunks)
            if len(text.strip()) < 40:
                return {
                    "stage": stage,
                    "ok": False,
                    "detail": f"流式输出过短（{len(text.strip())} 字），模型可能不支持流式或被网关截断",
                }
            detail = f"流式输出 {len(text.strip())} 字"
        else:
            # The reasoning roles all ask for schema-shaped JSON, so the probe
            # has to prove the endpoint honours json mode at a real budget.
            request = LLMRequest(
                model=model,
                system="Return only valid JSON matching the requested shape.",
                messages=[
                    LLMMessage(
                        content=(
                            'Return a JSON object shaped exactly like '
                            '{"summary": string, "steps": [string, string], "score": number}. '
                            "Fill it with any plausible content about a rainy train station."
                        )
                    )
                ],
                temperature=0,
                max_output_tokens=_PREFLIGHT_REASONING_TOKENS,
                json_mode=True,
                extra_body=extra,
                role="director",
            )
            response = await provider.generate_text(request)
            try:
                parsed = json.loads(response.text)
            except json.JSONDecodeError:
                return {
                    "stage": stage,
                    "ok": False,
                    "detail": "返回内容不是合法 JSON，该模型无法承担推理类角色",
                }
            if not isinstance(parsed, dict) or "summary" not in parsed:
                return {
                    "stage": stage,
                    "ok": False,
                    "detail": "返回的 JSON 结构不符合要求，推理类角色会持续失败",
                }
            detail = "结构化输出正常"
    except Exception as exc:
        logger.warning(
            "endpoint preflight failed endpoint=%s stage=%s error=%s",
            row.id,
            stage,
            type(exc).__name__,
        )
        return {"stage": stage, "ok": False, "detail": _explain(exc, row)}
    elapsed = (datetime.now(UTC) - started).total_seconds()
    return {"stage": stage, "ok": True, "detail": f"{detail}，耗时 {elapsed:.1f} 秒"}


def _explain(exc: Exception, row: PlatformLlmEndpointORM) -> str:
    """Turn a transport failure into the thing an operator should change."""

    name = type(exc).__name__
    text = str(exc)
    if "404" in text:
        hint = ""
        if row.provider in {"compatible", "openai"} and not row.base_url.rstrip("/").endswith(
            ("/v1", "/v1beta", "/openai")
        ):
            # The client appends /chat/completions verbatim, so a base URL that
            # stops at the host is the single most common cause of a 404 here.
            hint = "：Base URL 通常需要以 /v1 结尾"
        return f"端点返回 404，请检查 Base URL 与模型名称{hint}"
    if "401" in text or "403" in text:
        return "端点拒绝了这个密钥（401/403），请检查 API Key 与账号权限"
    if "429" in text:
        return "端点限流（429），当前额度或并发不足"
    if "Timeout" in name or "timeout" in text.lower():
        return "请求超时。游玩时要连续流式输出上千字，这个端点很可能撑不住一整回合"
    return f"连接失败（{name}）"


@router.post("/{endpoint_id}/test")
async def test_endpoint(
    endpoint_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    await rate_limiter.check(
        f"llm-endpoint-test:{principal.user_id}", 6, 60, redis_url=settings.redis_url
    )
    row = await uow.session.get(PlatformLlmEndpointORM, endpoint_id)
    if row is None:
        raise HTTPException(status_code=404, detail="endpoint not found")

    stages = [
        await _probe(row, settings, "narrative"),
        await _probe(row, settings, "reasoning"),
    ]
    ok = all(bool(stage["ok"]) for stage in stages)
    now = datetime.now(UTC)
    if ok:
        row.last_ok_at = now
        row.consecutive_failures = 0
        row.last_error = ""
    else:
        row.last_error_at = now
        row.last_error = str(next(s["detail"] for s in stages if not s["ok"]))[:200]
        row.consecutive_failures += 1
    uow.session.add(
        _audit(
            request,
            principal,
            "platform_llm_endpoint.tested",
            row.id,
            {"ok": ok, "stages": stages},
        )
    )
    await uow.commit()
    return {"ok": ok, "stages": stages, "endpoint": endpoint_view(row)}


class ReorderRequest(BaseModel):
    order: list[str] = Field(min_length=1, max_length=_MAX_ENDPOINTS)


@router.post("/reorder")
async def reorder_endpoints(
    body: ReorderRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_role_csrf("admin"))],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, object]:
    await set_tenant_context(uow.session, principal.user_id)
    rows = {row.id: row for row in await load_platform_endpoints(uow.session)}
    unknown = [item for item in body.order if item not in rows]
    if unknown:
        raise HTTPException(status_code=422, detail="endpoint not found")
    for index, endpoint_id in enumerate(body.order):
        rows[endpoint_id].priority = index
    uow.session.add(
        _audit(request, principal, "platform_llm_endpoint.reordered", "-", {"order": body.order})
    )
    await uow.commit()
    ordered = await load_platform_endpoints(uow.session)
    return {"items": [endpoint_view(row) for row in ordered]}

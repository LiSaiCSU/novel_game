"""Safe, dynamically reloadable configuration for the platform-funded LLM."""

from __future__ import annotations

import json
from ipaddress import ip_address
from urllib.parse import urlsplit

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.security import SecretBox
from database.models.platform import PlatformLlmConfigORM, PlatformLlmEndpointORM
from engine.core.config import Settings

PLATFORM_LLM_CONFIG_ID = "00000000-0000-0000-0000-000000000002"
SUPPORTED_PLATFORM_PROVIDERS = frozenset({"openai", "anthropic", "compatible"})


def normalize_public_api_base_url(value: str, *, required: bool = False) -> str:
    """Reject credential-bearing and local endpoints to prevent admin-console SSRF."""
    value = value.strip().rstrip("/")
    if not value:
        if required:
            raise ValueError("兼容模型必须填写 API Base URL")
        return ""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("API Base URL 必须是无账号信息的公网 HTTPS 地址")
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".local"):
        raise ValueError("API Base URL 不能指向本机或局域网服务")
    try:
        address = ip_address(hostname)
    except ValueError:
        return value
    if not address.is_global:
        raise ValueError("API Base URL 不能指向私有网络")
    return value


def _environment_has_key(settings: Settings, provider: str) -> bool:
    if settings.llm_api_key.strip() or settings.llm_api_keys.strip():
        return True
    return bool(
        {
            "openai": settings.openai_api_key,
            "anthropic": settings.anthropic_api_key,
            "compatible": settings.compatible_api_key,
        }.get(provider, "").strip()
    )


async def load_platform_llm_config(
    session: AsyncSession, settings: Settings
) -> tuple[Settings, PlatformLlmConfigORM | None]:
    """Return effective settings, falling back to the root-only environment."""
    row = await session.get(PlatformLlmConfigORM, PLATFORM_LLM_CONFIG_ID)
    if row is None:
        return settings, None

    narrative_model = row.model.strip()
    reasoning_model = (
        row.reasoning_model.strip()
        if row.reasoning_enabled and row.reasoning_model.strip()
        else narrative_model
    )
    narrative_extra_body = dict(row.extra_body or {})
    reasoning_extra_body = (
        dict(row.reasoning_extra_body or {})
        if row.reasoning_enabled
        else narrative_extra_body
    )

    update: dict[str, object] = {
        "llm_provider": row.provider if row.enabled else "null",
        "llm_base_url": row.base_url,
        "llm_model": narrative_model,
        "llm_extra_body": json.dumps(narrative_extra_body, ensure_ascii=False),
        "llm_reasoning_extra_body": json.dumps(reasoning_extra_body, ensure_ascii=False),
        # Structured roles use the reasoning profile.  The visible prose role
        # stays on the narrative profile.  Explicit assignments also prevent
        # environment role overrides from leaking into database configuration.
        "intent_model": reasoning_model,
        "npc_model": reasoning_model,
        "npc_major_model": reasoning_model,
        "director_model": reasoning_model,
        "steward_model": reasoning_model,
        "narrative_model": narrative_model,
        "memory_model": reasoning_model,
        "embedding_model": "",
    }
    if row.encrypted_secret:
        secret = SecretBox(settings.credential_encryption_key).decrypt(row.encrypted_secret)
        update.update(
            {
                "llm_api_key": secret,
                "llm_api_keys": "",
                "openai_api_key": "",
                "anthropic_api_key": "",
                "compatible_api_key": "",
            }
        )
    return settings.model_copy(update=update), row


def platform_llm_view(settings: Settings, row: PlatformLlmConfigORM | None) -> dict[str, object]:
    provider = row.provider if row else settings.llm_provider
    enabled = row.enabled if row else provider != "null"
    narrative_model = row.model if row else (settings.narrative_model or settings.llm_model)
    environment_reasoning_model = next(
        (
            value
            for value in (
                settings.director_model,
                settings.steward_model,
                settings.npc_major_model,
                settings.npc_model,
                settings.intent_model,
                settings.memory_model,
            )
            if value
        ),
        settings.llm_model,
    )
    reasoning_enabled = (
        row.reasoning_enabled
        if row
        else bool(environment_reasoning_model and environment_reasoning_model != narrative_model)
    )
    reasoning_model = (
        (row.reasoning_model or narrative_model) if row else environment_reasoning_model
    )
    base_url = row.base_url if row else settings.llm_base_url
    key_configured = (
        bool(row.encrypted_secret)
        if row and row.encrypted_secret
        else _environment_has_key(settings, provider)
    )
    narrative_extra_body = (
        dict(row.extra_body or {}) if row else _environment_extra_body(settings.llm_extra_body)
    )
    reasoning_extra_body = (
        dict(row.reasoning_extra_body or {})
        if row and row.reasoning_enabled
        else _environment_extra_body(settings.llm_reasoning_extra_body)
        if not row and settings.llm_reasoning_extra_body.strip()
        else narrative_extra_body
    )
    return {
        "enabled": enabled,
        "provider": provider,
        # Legacy aliases remain until the v1 compatibility window closes.
        "model": narrative_model,
        "base_url": base_url,
        "extra_body": narrative_extra_body,
        "narrative_model": narrative_model,
        "narrative_extra_body": narrative_extra_body,
        "reasoning_enabled": reasoning_enabled,
        "reasoning_model": reasoning_model or narrative_model,
        "reasoning_extra_body": reasoning_extra_body,
        "role_assignments": {
            "narrative": ["narrative"],
            "reasoning": ["intent", "npc", "npc_major", "director", "steward", "memory"],
        },
        "key_configured": key_configured,
        "key_hint": (
            row.key_hint if row and row.key_hint else ("已由服务器配置" if key_configured else "")
        ),
        "source": "database" if row else "environment",
        "updated_at": row.updated_at if row else None,
    }


def _environment_extra_body(raw: str) -> dict[str, object]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


async def load_platform_endpoints(session: AsyncSession) -> list[PlatformLlmEndpointORM]:
    """Return the configured chain, most preferred first."""

    rows = await session.scalars(
        sa.select(PlatformLlmEndpointORM).order_by(
            PlatformLlmEndpointORM.priority, PlatformLlmEndpointORM.name
        )
    )
    return list(rows)


def endpoint_chain_payload(
    rows: list[PlatformLlmEndpointORM], settings: Settings
) -> list[dict[str, object]]:
    """Decrypt the enabled endpoints into the shape ``build_provider`` reads.

    A credential that cannot be decrypted is dropped rather than raised: one
    stale key must not take down a chain whose whole purpose is to survive a
    single endpoint going bad.
    """

    box = SecretBox(settings.credential_encryption_key)
    payload: list[dict[str, object]] = []
    for row in rows:
        if not row.enabled:
            continue
        secret = ""
        if row.encrypted_secret:
            try:
                secret = box.decrypt(row.encrypted_secret)
            except ValueError:
                continue
        payload.append(
            {
                "id": row.id,
                "name": row.name or row.provider,
                "provider": row.provider,
                "base_url": row.base_url,
                "api_key": secret,
                "narrative_model": row.narrative_model,
                "reasoning_model": row.reasoning_model or row.narrative_model,
                "extra_body": dict(row.narrative_extra_body or {}),
            }
        )
    return payload


async def load_platform_llm_settings(
    session: AsyncSession, settings: Settings
) -> tuple[Settings, list[PlatformLlmEndpointORM]]:
    """Effective settings for the whole endpoint chain.

    The first enabled endpoint supplies the model names the ``ModelRouter``
    resolves per role; the rest ride along in ``llm_endpoints`` so the provider
    can fail over without the router knowing anything about endpoints.
    """

    rows = await load_platform_endpoints(session)
    payload = endpoint_chain_payload(rows, settings)
    if not payload:
        # No usable chain: keep the historical single-row/environment behaviour.
        effective, _row = await load_platform_llm_config(session, settings)
        return effective, rows

    head = payload[0]
    narrative_model = str(head["narrative_model"])
    reasoning_model = str(head["reasoning_model"]) or narrative_model
    extra_body = json.dumps(head.get("extra_body") or {}, ensure_ascii=False)
    update: dict[str, object] = {
        "llm_provider": str(head["provider"]),
        "llm_base_url": str(head["base_url"]),
        "llm_api_key": str(head["api_key"]),
        "llm_api_keys": "",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "compatible_api_key": "",
        "llm_model": narrative_model,
        "llm_extra_body": extra_body,
        "llm_reasoning_extra_body": extra_body,
        "narrative_model": narrative_model,
        "intent_model": reasoning_model,
        "npc_model": reasoning_model,
        "npc_major_model": reasoning_model,
        "director_model": reasoning_model,
        "steward_model": reasoning_model,
        "memory_model": reasoning_model,
        "embedding_model": "",
        "llm_endpoints": json.dumps(payload, ensure_ascii=False),
    }
    return settings.model_copy(update=update), rows


def endpoint_view(row: PlatformLlmEndpointORM) -> dict[str, object]:
    """Operator-facing state. The secret itself is never returned."""

    return {
        "id": row.id,
        "name": row.name,
        "enabled": row.enabled,
        "priority": row.priority,
        "provider": row.provider,
        "base_url": row.base_url,
        "narrative_model": row.narrative_model,
        "reasoning_model": row.reasoning_model or row.narrative_model,
        "narrative_extra_body": dict(row.narrative_extra_body or {}),
        "reasoning_extra_body": dict(row.reasoning_extra_body or {}),
        "key_configured": bool(row.encrypted_secret),
        "key_hint": row.key_hint,
        "last_ok_at": row.last_ok_at,
        "last_error_at": row.last_error_at,
        "last_error": row.last_error,
        "consecutive_failures": row.consecutive_failures,
        "updated_at": row.updated_at,
    }

"""Safe, dynamically reloadable configuration for the platform-funded LLM."""

from __future__ import annotations

import json
from ipaddress import ip_address
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.security import SecretBox
from database.models.platform import PlatformLlmConfigORM
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

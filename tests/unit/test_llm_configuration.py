from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.api.runtime import _byok_runtime_settings
from engine.core.config import Settings
from engine.core.errors import LLMError
from engine.core.types import LLMRole
from engine.llm.budget import BudgetedProvider
from engine.llm.provider import LLMMessage, LLMRequest
from engine.llm.providers import CompatibleProvider, ProviderPool, ScriptedProvider, build_provider
from engine.llm.router import ModelRouter


def test_default_model_fills_all_text_roles_and_allows_overrides() -> None:
    router = ModelRouter(
        Settings(
            llm_model="default",
            intent_model="",
            npc_model="",
            npc_major_model="",
            director_model="",
            steward_model="",
            narrative_model="writer",
            memory_model="",
            embedding_model="",
        )
    )

    assert router.choose(LLMRole.INTENT).model == "default"
    assert router.choose(LLMRole.NPC).model == "default"
    assert router.choose(LLMRole.NPC_MAJOR).model == "default"
    assert router.choose(LLMRole.DIRECTOR).model == "default"
    assert router.choose(LLMRole.STEWARD).model == "default"
    assert router.choose(LLMRole.NARRATIVE).model == "writer"
    assert router.choose(LLMRole.MEMORY).model == "default"
    assert router.choose(LLMRole.EMBEDDING).model == ""


def test_byok_model_replaces_every_platform_role_override() -> None:
    platform = Settings(
        llm_model="platform-default",
        intent_model="platform-intent",
        npc_model="platform-npc",
        npc_major_model="platform-major",
        director_model="platform-director",
        steward_model="platform-steward",
        narrative_model="platform-writer",
        memory_model="platform-memory",
        embedding_model="platform-embedding",
    )

    private = _byok_runtime_settings(
        platform,
        provider="compatible",
        secret="private-key",
        model="player-model",
        base_url="https://api.deepseek.com",
    )
    router = ModelRouter(private)

    assert all(
        router.choose(role).model == "player-model"
        for role in (
            LLMRole.INTENT,
            LLMRole.NPC,
            LLMRole.NPC_MAJOR,
            LLMRole.DIRECTOR,
            LLMRole.STEWARD,
            LLMRole.NARRATIVE,
            LLMRole.MEMORY,
        )
    )
    assert router.choose(LLMRole.EMBEDDING).model == ""
    assert private.llm_provider == "compatible"
    assert private.llm_base_url == "https://api.deepseek.com"


def test_production_configuration_fails_closed_when_security_is_incomplete() -> None:
    with pytest.raises(ValueError, match="unsafe production configuration"):
        Settings(app_env="production")


def test_production_configuration_accepts_explicit_secure_services() -> None:
    settings = Settings(
        app_env="production",
        debug_mode=False,
        database_url="postgresql+asyncpg://service@db/narrative",
        redis_url="redis://cache/0",
        auth_cookie_secure=True,
        auth_pepper="p" * 32,
        credential_encryption_key="k" * 32,
        cors_origins="https://game.example",
        public_app_url="https://game.example",
        object_store_backend="s3",
        require_verified_email=True,
        metrics_token="m" * 32,
        clamav_host="antivirus.internal",
        sentry_dsn="https://public@example.invalid/1",
    )

    assert settings.app_env == "production"


def test_llm_price_table_uses_exact_then_provider_wildcard() -> None:
    from apps.api.runtime import llm_cost_microunits

    settings = Settings(
        llm_price_table={
            "openai:exact": {"input_per_million": 2_000_000, "output_per_million": 8_000_000},
            "openai:*": {"input_per_million": 1_000_000, "output_per_million": 4_000_000},
        }
    )
    assert llm_cost_microunits(settings, "openai", "exact", 1_000, 500) == 6_000
    assert llm_cost_microunits(settings, "openai", "other", 1_000, 500) == 3_000


def test_unified_compatible_settings_build_a_single_provider() -> None:
    settings = Settings(
        llm_provider="compatible",
        llm_api_key="key-one",
        llm_api_keys="",
        llm_base_url="https://example.test/v1",
        compatible_api_key="",
    )

    provider = build_provider(settings)

    assert isinstance(provider, CompatibleProvider)
    assert provider.api_key == "key-one"
    assert provider.base_url == "https://example.test/v1"


def test_multiple_unified_keys_build_a_deduplicated_pool() -> None:
    settings = Settings(
        llm_provider="compatible",
        llm_api_key="key-one",
        llm_api_keys="key-one, key-two\nkey-three;key-two",
        llm_base_url="https://example.test/v1",
        compatible_api_key="legacy-key-is-ignored",
    )

    provider = build_provider(settings)

    assert isinstance(provider, ProviderPool)
    assert [item.api_key for item in provider.providers] == [
        "key-one",
        "key-two",
        "key-three",
    ]


@pytest.mark.asyncio
async def test_provider_pool_round_robins_calls() -> None:
    first = ScriptedProvider(default="first")
    second = ScriptedProvider(default="second")
    pool = ProviderPool([first, second])
    request = LLMRequest(model="model", messages=[])

    responses = [await pool.generate_text(request) for _ in range(3)]

    assert [response.text for response in responses] == ["first", "second", "first"]
    assert [len(first.calls), len(second.calls)] == [2, 1]


@pytest.mark.asyncio
async def test_turn_budget_rejects_before_dispatch_and_accumulates_calls() -> None:
    provider = ScriptedProvider(default="ok")
    guarded = BudgetedProvider(provider, token_limit=26)
    request = LLMRequest(
        model="model",
        messages=[LLMMessage(content="四个汉字")],
        max_output_tokens=8,
    )

    await guarded.generate_text(request)
    await guarded.generate_text(request)
    with pytest.raises(LLMError, match="budget exhausted"):
        await guarded.generate_text(request)

    assert len(provider.calls) == 2


def test_legacy_compatible_configuration_still_works() -> None:
    settings = SimpleNamespace(
        llm_provider="compatible",
        llm_timeout_seconds=60,
        llm_api_key="",
        llm_api_keys="",
        llm_base_url="",
        compatible_api_key="legacy-key",
        compatible_base_url="https://legacy.test/v1",
    )

    provider = build_provider(settings)

    assert isinstance(provider, CompatibleProvider)
    assert provider.api_key == "legacy-key"
    assert provider.base_url == "https://legacy.test/v1"

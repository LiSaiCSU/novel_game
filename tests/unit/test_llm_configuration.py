from __future__ import annotations

from types import SimpleNamespace

import pytest

from engine.core.config import Settings
from engine.core.types import LLMRole
from engine.llm.provider import LLMRequest
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

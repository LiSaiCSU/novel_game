"""Administrator management of the platform model chain.

The platform used to hold one model connection, and its connection test asked
for ninety-six tokens over a non-streaming request. That combination is what
let an administrator swap the API, see a green check, and then watch every turn
fail: play streams a long scene and demands schema-shaped JSON, neither of
which the old probe ever attempted.
"""

from __future__ import annotations

import pytest

from apps.api.llm_config import (
    endpoint_chain_payload,
    load_platform_endpoints,
    load_platform_llm_settings,
)
from apps.api.security import SecretBox
from database.models.platform import PlatformLlmEndpointORM
from engine.llm.providers import build_provider

TEST_SETTINGS_KEY = "integration-test-credential-key"


def _settings():
    from engine.core.config import Settings

    return Settings(credential_encryption_key=TEST_SETTINGS_KEY)


async def _admin(client, email: str = "llm-admin@example.com") -> str:
    """Register an administrator and clear the MFA step-up these routes need."""
    import time

    import database.session as db_session
    from apps.api.security import _totp
    from database.models.platform import UserRoleORM
    from engine.core.ids import new_id

    password = "correct-horse-admin"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": "运维"},
    )
    assert registered.status_code == 201, registered.text
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        session.add(UserRoleORM(id=new_id(), user_id=registered.json()["id"], role="admin"))
        await session.commit()
    csrf = client.cookies.get("ng_csrf")
    enrollment = await client.post(
        "/api/v1/auth/mfa/enroll", headers={"X-CSRF-Token": csrf}, json={"password": password}
    )
    assert enrollment.status_code == 200, enrollment.text
    confirmation = await client.post(
        "/api/v1/auth/mfa/confirm",
        headers={"X-CSRF-Token": csrf},
        json={"code": _totp(enrollment.json()["secret"], int(time.time() // 30))},
    )
    assert confirmation.status_code == 200, confirmation.text
    return csrf


def _payload(**overrides) -> dict:
    body = {
        "name": "主用端点",
        "enabled": True,
        "priority": 0,
        "provider": "compatible",
        "base_url": "https://api.example.com/v1",
        "narrative_model": "prose-model",
        "reasoning_model": "cheap-model",
        "api_key": "sk-primary-key",
    }
    body.update(overrides)
    return body


async def test_administrator_can_run_more_than_one_endpoint(client) -> None:
    csrf = await _admin(client)

    first = await client.post(
        "/api/v1/admin/llm-endpoints", headers={"X-CSRF-Token": csrf}, json=_payload()
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/api/v1/admin/llm-endpoints",
        headers={"X-CSRF-Token": csrf},
        json=_payload(
            name="备用网关",
            priority=10,
            base_url="https://backup.example.com/v1",
            narrative_model="gateway-model",
            api_key="sk-backup-key",
        ),
    )
    assert second.status_code == 201, second.text

    listing = await client.get("/api/v1/admin/llm-endpoints")
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert [item["name"] for item in items] == ["主用端点", "备用网关"]
    # The secret must never travel back to a browser, only the hint.
    assert all("api_key" not in item and "encrypted_secret" not in item for item in items)
    assert items[0]["key_hint"].endswith("-key"[-4:]) or items[0]["key_hint"].startswith("…")


async def test_reordering_changes_which_endpoint_is_tried_first(client) -> None:
    csrf = await _admin(client, "reorder-admin@example.com")
    a = (
        await client.post(
            "/api/v1/admin/llm-endpoints", headers={"X-CSRF-Token": csrf}, json=_payload()
        )
    ).json()
    b = (
        await client.post(
            "/api/v1/admin/llm-endpoints",
            headers={"X-CSRF-Token": csrf},
            json=_payload(name="备用", priority=10, api_key="sk-b"),
        )
    ).json()

    reordered = await client.post(
        "/api/v1/admin/llm-endpoints/reorder",
        headers={"X-CSRF-Token": csrf},
        json={"order": [b["id"], a["id"]]},
    )

    assert reordered.status_code == 200
    assert [item["name"] for item in reordered.json()["items"]] == ["备用", "主用端点"]


async def test_the_last_usable_endpoint_cannot_be_deleted_by_accident(client) -> None:
    csrf = await _admin(client, "delete-admin@example.com")
    created = (
        await client.post(
            "/api/v1/admin/llm-endpoints", headers={"X-CSRF-Token": csrf}, json=_payload()
        )
    ).json()

    refused = await client.delete(
        f"/api/v1/admin/llm-endpoints/{created['id']}", headers={"X-CSRF-Token": csrf}
    )

    # Removing the only route to a model silently disables the whole site.
    assert refused.status_code == 409
    assert "最后一个可用端点" in refused.json()["detail"]


async def test_a_base_url_without_a_path_is_rejected_before_it_can_404(client) -> None:
    csrf = await _admin(client, "url-admin@example.com")

    created = await client.post(
        "/api/v1/admin/llm-endpoints",
        headers={"X-CSRF-Token": csrf},
        json=_payload(base_url="http://api.example.com/v1"),
    )

    assert created.status_code == 422
    assert "HTTPS" in created.json()["detail"]


async def test_chain_payload_orders_by_priority_and_skips_disabled(client) -> None:
    import database.session as db_session
    from engine.core.ids import new_id

    settings = _settings()
    box = SecretBox(settings.credential_encryption_key)
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        session.add_all(
            [
                PlatformLlmEndpointORM(
                    id=new_id(),
                    name="backup",
                    priority=10,
                    provider="compatible",
                    base_url="https://backup.example.com/v1",
                    encrypted_secret=box.encrypt("sk-backup"),
                    narrative_model="gateway-model",
                    reasoning_model="gateway-mini",
                ),
                PlatformLlmEndpointORM(
                    id=new_id(),
                    name="primary",
                    priority=0,
                    provider="compatible",
                    base_url="https://api.example.com/v1",
                    encrypted_secret=box.encrypt("sk-primary"),
                    narrative_model="prose-model",
                    reasoning_model="cheap-model",
                    narrative_extra_body={"thinking": {"type": "disabled"}},
                    reasoning_extra_body={
                        "thinking": {"type": "enabled"},
                        "reasoning_effort": "low",
                    },
                ),
                PlatformLlmEndpointORM(
                    id=new_id(),
                    name="retired",
                    priority=5,
                    enabled=False,
                    provider="compatible",
                    base_url="https://old.example.com/v1",
                    encrypted_secret=box.encrypt("sk-old"),
                    narrative_model="old-model",
                ),
            ]
        )
        await session.commit()
        rows = await load_platform_endpoints(session)
        effective, _ = await load_platform_llm_settings(session, settings)

    payload = endpoint_chain_payload(rows, settings)

    assert [item["name"] for item in payload] == ["primary", "backup"]
    assert [item["api_key"] for item in payload] == ["sk-primary", "sk-backup"]
    assert payload[0]["narrative_extra_body"] == {"thinking": {"type": "disabled"}}
    assert payload[0]["reasoning_extra_body"] == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "low",
    }
    assert effective.llm_extra_body == "{}"
    assert effective.llm_reasoning_extra_body == "{}"


def test_build_provider_produces_a_failover_chain_with_per_endpoint_models() -> None:
    import json

    from engine.core.config import Settings
    from engine.llm.failover import FailoverProvider

    settings = Settings(
        llm_endpoints=json.dumps(
            [
                {
                    "name": "primary",
                    "provider": "compatible",
                    "base_url": "https://api.example.com/v1",
                    "api_key": "sk-primary",
                    "narrative_model": "prose-model",
                    "reasoning_model": "cheap-model",
                    "narrative_extra_body": {"thinking": {"type": "disabled"}},
                    "reasoning_extra_body": {
                        "thinking": {"type": "enabled"},
                        "reasoning_effort": "low",
                    },
                },
                {
                    "name": "backup",
                    "provider": "compatible",
                    "base_url": "https://backup.example.com/v1",
                    "api_key": "sk-backup",
                    "narrative_model": "gateway-model",
                    "reasoning_model": "gateway-mini",
                },
            ]
        )
    )

    provider = build_provider(settings)

    assert isinstance(provider, FailoverProvider)
    assert [target.name for target in provider.targets] == ["primary", "backup"]
    # Each endpoint names the roles in its own vocabulary, which is exactly what
    # a single shared model name could not express.
    assert provider.targets[0].models["narrative"] == "prose-model"
    assert provider.targets[0].models["director"] == "cheap-model"
    assert provider.targets[1].models["narrative"] == "gateway-model"
    assert provider.targets[1].models["director"] == "gateway-mini"

    from engine.llm.provider import LLMRequest

    narrative = provider.targets[0].prepare(
        LLMRequest(model="ignored", messages=[], role="narrative", extra_body={"client": True})
    )
    reasoning = provider.targets[0].prepare(
        LLMRequest(model="ignored", messages=[], role="director", extra_body={"client": True})
    )
    assert narrative.extra_body == {
        "client": True,
        "thinking": {"type": "disabled"},
    }
    assert reasoning.extra_body == {
        "client": True,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "low",
    }


@pytest.mark.parametrize(
    ("error_text", "expected"),
    [
        ("Client error '404 Not Found' for url ...", "404"),
        ("Client error '401 Unauthorized'", "401/403"),
        ("Client error '429 Too Many Requests'", "429"),
    ],
)
def test_preflight_explains_transport_failures_in_operator_terms(
    error_text: str, expected: str
) -> None:
    from apps.api.routers.llm_endpoints import _explain

    row = PlatformLlmEndpointORM(
        id="x", provider="compatible", base_url="https://api.example.com"
    )

    message = _explain(RuntimeError(error_text), row)

    assert expected in message


def test_preflight_names_the_missing_version_path_behind_a_404() -> None:
    from apps.api.routers.llm_endpoints import _explain

    # The client appends /chat/completions verbatim, so a host-only base URL is
    # the single most common cause of the 404 an operator sees here.
    stopped_at_host = PlatformLlmEndpointORM(
        id="x", provider="compatible", base_url="https://cf.api.fan"
    )
    already_versioned = PlatformLlmEndpointORM(
        id="y", provider="compatible", base_url="https://cf.api.fan/v1"
    )
    failure = RuntimeError("Client error '404 Not Found' for url ...")

    assert "/v1" in _explain(failure, stopped_at_host)
    assert "/v1 结尾" not in _explain(failure, already_versioned)


def test_preflight_calls_a_timeout_what_it_will_mean_during_play() -> None:
    from apps.api.routers.llm_endpoints import _explain

    row = PlatformLlmEndpointORM(id="x", provider="compatible", base_url="https://a.example/v1")

    message = _explain(TimeoutError("ReadTimeout"), row)

    assert "超时" in message and "回合" in message

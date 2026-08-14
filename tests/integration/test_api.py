"""API surface tests (Prompt sections 50, 52, 53).

Exercised against a real ASGI app backed by a real (in-memory SQLite) database.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(monkeypatch, tmp_path, pack, registry):
    """A fully isolated app: its own database file, its own orchestrator, no LLM.

    Every seam the app uses to reach global state is redirected here, so a test
    run can never touch the developer's ./data/game.db.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import apps.api.deps as deps
    import database.session as db_session
    from apps.api.main import create_app
    from database.base import Base
    from engine.core.config import Settings
    from engine.orchestrator.factory import build_orchestrator

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}",
        llm_provider="null",
        debug_mode=True,
        embedding_dim=128,
        require_verified_email=False,
        auth_pepper="integration-test-pepper",
        credential_encryption_key="integration-test-credential-key",
        assets_dir=str(tmp_path / "assets"),
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    # Routers may have captured these dependency callables during an earlier
    # test-module import. Keep their identities for FastAPI's override map.
    settings_dependency = deps.settings_dep
    orchestrator_dependency = deps.orchestrator_dep
    pack_dependency = deps.pack_dep

    # database.session is looked up by module global at call time
    monkeypatch.setattr(db_session, "get_engine", lambda *_a, **_k: engine)
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda *_a, **_k: maker)
    # apps.api.deps imported the name directly, so patch it there as well
    monkeypatch.setattr(deps, "get_sessionmaker", lambda *_a, **_k: maker)
    monkeypatch.setattr(deps, "settings_dep", lambda: settings)

    orchestrator = build_orchestrator(settings=settings, pack=pack, registry=registry)
    monkeypatch.setattr(deps, "orchestrator_dep", lambda: orchestrator)

    app = create_app()
    # dependency_overrides is the sanctioned seam for the Depends(...) defaults
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[pack_dependency] = lambda: pack

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as c,
        app.router.lifespan_context(app),
    ):
        yield c
    await engine.dispose()


async def test_health(client) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_checks_database(client) -> None:
    response = await client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_metrics_use_route_templates_and_prometheus_format(client) -> None:
    trace_id = "1" * 32
    health = await client.get(
        "/api/health", headers={"traceparent": f"00-{trace_id}-{'2' * 16}-01"}
    )
    assert health.headers["traceparent"].startswith(f"00-{trace_id}-")
    response = await client.get("/api/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "narrative_http_requests_total" in response.text
    assert 'route="/api/health"' in response.text


async def test_admin_quota_and_role_controls_are_authorized_and_audited(client) -> None:
    import time

    import database.session as db_session
    from apps.api.security import _totp
    from database.models.platform import ProductEventORM, UserORM, UserRoleORM
    from engine.core.ids import new_id

    regular = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "quota-player@example.com",
            "password": "correct-horse-player",
            "display_name": "额度玩家",
        },
    )
    assert regular.status_code == 201
    regular_id = regular.json()["id"]
    regular_csrf = client.cookies.get("ng_csrf")
    assert (await client.get("/api/v1/admin/users")).status_code == 403
    forbidden = await client.put(
        f"/api/v1/admin/users/{regular_id}/quota",
        headers={"X-CSRF-Token": regular_csrf},
        json={"monthly_tokens": 300_000, "reason": "越权尝试"},
    )
    assert forbidden.status_code == 403

    administrator = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "quota-admin@example.com",
            "password": "correct-horse-admin",
            "display_name": "平台管理员",
        },
    )
    assert administrator.status_code == 201
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        session.add(UserRoleORM(id=new_id(), user_id=administrator.json()["id"], role="admin"))
        await session.commit()
    admin_csrf = client.cookies.get("ng_csrf")
    blocked_until_mfa = await client.get("/api/v1/admin/users")
    assert blocked_until_mfa.status_code == 403
    assert blocked_until_mfa.json()["detail"]["code"] == "admin_mfa_enrollment_required"
    enrollment = await client.post(
        "/api/v1/auth/mfa/enroll",
        headers={"X-CSRF-Token": admin_csrf},
        json={"password": "correct-horse-admin"},
    )
    assert enrollment.status_code == 200, enrollment.text
    secret = enrollment.json()["secret"]
    confirmation = await client.post(
        "/api/v1/auth/mfa/confirm",
        headers={"X-CSRF-Token": admin_csrf},
        json={"code": _totp(secret, int(time.time() // 30))},
    )
    assert confirmation.status_code == 200, confirmation.text
    assert len(confirmation.json()["recovery_codes"]) == 10
    listing = await client.get("/api/v1/admin/users?query=quota-player")
    assert listing.status_code == 200, listing.text
    assert listing.json()["items"][0]["id"] == regular_id
    changed = await client.put(
        f"/api/v1/admin/users/{regular_id}/quota",
        headers={"X-CSRF-Token": admin_csrf},
        json={"monthly_tokens": 345_000, "reason": "封闭测试额度"},
    )
    assert changed.status_code == 200, changed.text
    roles = await client.put(
        f"/api/v1/admin/users/{regular_id}/roles",
        headers={"X-CSRF-Token": admin_csrf},
        json={"roles": ["player", "reviewer"], "reason": "加入审核轮值"},
    )
    assert roles.status_code == 200, roles.text
    assert roles.json()["roles"] == ["player", "reviewer"]
    async with maker() as session:
        stored = await session.get(UserORM, regular_id)
        assert stored is not None and stored.platform_quota_monthly == 345_000
        stored.analytics_consent = True
        session.add_all(
            [
                ProductEventORM(
                    id=new_id(),
                    user_id=regular_id,
                    event_name="playthrough_started",
                    event_properties={"scenario_key": "campus"},
                ),
                ProductEventORM(
                    id=new_id(),
                    user_id=regular_id,
                    event_name="action_completed",
                    event_properties={"turn_number": 3, "steps": 1, "degraded": False},
                ),
            ]
        )
        await session.commit()
    funnel = await client.get("/api/v1/admin/product-funnel?days=30")
    assert funnel.status_code == 200, funnel.text
    assert funnel.json()["consented_users"] == 1
    player_stages = {stage["key"]: stage for stage in funnel.json()["player"]}
    assert player_stages["playthrough_started"]["unique_users"] == 1
    assert player_stages["first_action"]["unique_users"] == 1
    assert player_stages["third_turn"]["unique_users"] == 1
    assert "user_id" not in funnel.text
    audits = (await client.get("/api/v1/creator/audit-logs?limit=20")).json()
    assert {row["action"] for row in audits} >= {"user.quota_changed", "user.roles_changed"}


async def test_admin_can_manage_and_test_platform_llm_without_secret_echo(
    client, monkeypatch
) -> None:
    import time

    import database.session as db_session
    from apps.api.security import SecretBox, _totp
    from database.models.platform import PlatformLlmConfigORM, UserRoleORM
    from engine.core.ids import new_id
    from engine.llm.providers import ScriptedProvider

    administrator = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "model-admin@example.com",
            "password": "correct-horse-model-admin",
            "display_name": "模型管理员",
        },
    )
    assert administrator.status_code == 201
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        session.add(UserRoleORM(id=new_id(), user_id=administrator.json()["id"], role="admin"))
        await session.commit()
    csrf = client.cookies.get("ng_csrf")
    enrollment = await client.post(
        "/api/v1/auth/mfa/enroll",
        headers={"X-CSRF-Token": csrf},
        json={"password": "correct-horse-model-admin"},
    )
    secret = enrollment.json()["secret"]
    confirmed = await client.post(
        "/api/v1/auth/mfa/confirm",
        headers={"X-CSRF-Token": csrf},
        json={"code": _totp(secret, int(time.time() // 30))},
    )
    assert confirmed.status_code == 200

    initial = await client.get("/api/v1/admin/llm-config")
    assert initial.status_code == 200
    assert initial.json()["source"] == "environment"
    production_key = "sk-platform-secret-1234"
    updated = await client.put(
        "/api/v1/admin/llm-config",
        headers={"X-CSRF-Token": csrf},
        json={
            "enabled": True,
            "provider": "compatible",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com",
            "api_key": production_key,
            "extra_body": {"thinking": {"type": "disabled"}},
            "reason": "接入生产模型",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["source"] == "database"
    assert updated.json()["key_hint"] == "…1234"
    assert production_key not in updated.text
    async with maker() as session:
        row = await session.get(PlatformLlmConfigORM, "00000000-0000-0000-0000-000000000002")
        assert row is not None and production_key not in (row.encrypted_secret or "")
        assert (
            SecretBox("integration-test-credential-key").decrypt(row.encrypted_secret or "")
            == production_key
        )

    monkeypatch.setattr(
        "apps.api.routers.admin.build_provider",
        lambda _settings: ScriptedProvider(default='{"status":"ok"}'),
    )
    tested = await client.post("/api/v1/admin/llm-config/test", headers={"X-CSRF-Token": csrf})
    assert tested.status_code == 200, tested.text
    assert tested.json()["status"] == "ok"
    assert production_key not in tested.text


async def test_mfa_recovery_code_is_single_use_and_totp_replay_is_rejected(client) -> None:
    import time

    import sqlalchemy as sa

    import database.session as db_session
    from apps.api.security import _totp
    from database.models.platform import AuthSessionORM

    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "mfa-player@example.com",
            "password": "correct-horse-mfa",
            "display_name": "双重验证玩家",
        },
    )
    assert registered.status_code == 201
    csrf = client.cookies.get("ng_csrf")
    enrollment = await client.post(
        "/api/v1/auth/mfa/enroll",
        headers={"X-CSRF-Token": csrf},
        json={"password": "correct-horse-mfa"},
    )
    secret = enrollment.json()["secret"]
    current_code = _totp(secret, int(time.time() // 30))
    confirmation = await client.post(
        "/api/v1/auth/mfa/confirm",
        headers={"X-CSRF-Token": csrf},
        json={"code": current_code},
    )
    recovery = confirmation.json()["recovery_codes"][0]
    replay = await client.post(
        "/api/v1/auth/mfa/step-up",
        headers={"X-CSRF-Token": csrf},
        json={"code": current_code},
    )
    assert replay.status_code == 400
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        # Session ids are deliberately unrelated to opaque cookie values.
        row = (
            (
                await session.execute(
                    sa.select(AuthSessionORM).where(
                        AuthSessionORM.user_id == registered.json()["id"]
                    )
                )
            )
            .scalars()
            .one()
        )
        row.mfa_verified_at = None
        await session.commit()
    first = await client.post(
        "/api/v1/auth/mfa/step-up",
        headers={"X-CSRF-Token": csrf},
        json={"code": recovery},
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/v1/auth/mfa/step-up",
        headers={"X-CSRF-Token": csrf},
        json={"code": recovery},
    )
    assert second.status_code == 400


async def test_new_device_login_is_detected_without_leaking_password_state(client) -> None:
    import sqlalchemy as sa

    import database.session as db_session
    from database.models.platform import AuditLogORM

    registered = await client.post(
        "/api/v1/auth/register",
        headers={"User-Agent": "First Device"},
        json={
            "email": "login-alert@example.com",
            "password": "correct-horse-alert",
            "display_name": "登录提醒",
        },
    )
    user_id = registered.json()["id"]
    failed = await client.post(
        "/api/v1/auth/login",
        headers={"User-Agent": "Suspicious Device", "X-Forwarded-For": "203.0.113.12"},
        json={"email": "login-alert@example.com", "password": "wrong-password"},
    )
    assert failed.status_code == 401
    logged_in = await client.post(
        "/api/v1/auth/login",
        headers={"User-Agent": "Second Device", "X-Forwarded-For": "203.0.113.19"},
        json={"email": "login-alert@example.com", "password": "correct-horse-alert"},
    )
    assert logged_in.status_code == 200
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        actions = set(
            (
                await session.execute(
                    sa.select(AuditLogORM.action).where(AuditLogORM.actor_id == user_id)
                )
            )
            .scalars()
            .all()
        )
    assert actions >= {"auth.login_failed", "auth.login_anomaly"}


async def test_creator_asset_is_sanitized_and_has_owner_checked_thumbnail(client) -> None:
    import io

    from PIL import Image

    from engine.contentpack.legacy_v2 import project_v1_as_v2
    from engine.contentpack.pack import load_content_pack
    from engine.core.config import get_settings

    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "asset-creator@example.com",
            "password": "correct-horse-assets",
            "display_name": "素材创作者",
        },
    )
    assert registered.status_code == 201
    document = project_v1_as_v2(
        load_content_pack(get_settings().content_path, "campus_romance_v1"),
        slug="asset-thumbnail-test",
    ).model_dump(mode="json")
    csrf = client.cookies.get("ng_csrf")
    project = await client.post(
        "/api/v1/creator/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "slug": "asset-thumbnail-test",
            "title": "素材测试",
            "document": document,
        },
    )
    assert project.status_code == 201, project.text
    image = Image.new("RGB", (800, 600), (151, 101, 126))
    payload = io.BytesIO()
    image.save(payload, format="PNG", pnginfo=None)
    uploaded = await client.post(
        f"/api/v1/creator/projects/{project.json()['id']}/assets",
        headers={"X-CSRF-Token": csrf},
        data={"key": "campus_cover", "kind": "cover", "alt_text": "春日校园"},
        files={"file": ("cover.png", payload.getvalue(), "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    thumbnail_url = uploaded.json()["thumbnail_url"]
    assert thumbnail_url and thumbnail_url.endswith(".thumb.webp")
    thumbnail = await client.get(thumbnail_url)
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"] == "image/webp"


async def test_creator_can_start_from_server_verified_template(client) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "template-author@example.com",
            "password": "correct-horse-template",
            "display_name": "模板作者",
        },
    )
    assert registered.status_code == 201
    templates = (await client.get("/api/v1/creator/templates")).json()
    assert {item["key"] for item in templates} == {"blank", "relationship_drama", "mystery"}
    assert next(item for item in templates if item["key"] == "mystery")["counts"] == {
        "locations": 3,
        "characters": 2,
        "facts": 1,
        "quests": 1,
        "plot_threads": 1,
        "author_tests": 2,
    }

    csrf = client.cookies.get("ng_csrf")
    created = await client.post(
        "/api/v1/creator/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "slug": "template-mystery",
            "title": "雾中来信",
            "summary": "每个人记得的闭馆时间都不同。",
            "template_key": "mystery",
        },
    )
    assert created.status_code == 201, created.text
    project = (await client.get(f"/api/v1/creator/projects/{created.json()['id']}")).json()
    document = project["document"]
    assert document["manifest"]["slug"] == "template-mystery"
    assert len(document["content"]["locations"]) == 3
    assert document["content"]["scenarios"][0]["initial_threads"] == ["missing_exhibit"]
    assert len(document["author_tests"]) == 2
    validated = await client.post(f"/api/v1/creator/projects/{created.json()['id']}/validate")
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    assert validated.json()["author_tests"]["passed_count"] == 2


async def test_release_gate_rejects_failed_or_missing_declared_author_tests(client) -> None:
    from apps.authoring.templates import build_project_template

    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "test-gate-author@example.com",
            "password": "correct-horse-test-gate",
            "display_name": "测试门禁作者",
        },
    )
    assert registered.status_code == 201
    csrf = client.cookies.get("ng_csrf")
    failed_document = build_project_template(
        "blank", title="失败测试作品", slug="failed-author-tests"
    ).model_dump(mode="json")
    failed_document["author_tests"][0]["assertions"][0]["expected"] = "missing_location"
    failed_project = await client.post(
        "/api/v1/creator/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "slug": "failed-author-tests",
            "title": "失败测试作品",
            "document": failed_document,
        },
    )
    assert failed_project.status_code == 201, failed_project.text
    failed_release = await client.post(
        f"/api/v1/creator/projects/{failed_project.json()['id']}/releases",
        headers={"X-CSRF-Token": csrf},
        json={"version": "1.0.0", "visibility": "private"},
    )
    assert failed_release.status_code == 422
    assert "AUTHOR_TESTS_FAILED" in failed_release.text

    missing_document = build_project_template(
        "blank", title="缺少测试作品", slug="missing-author-tests"
    ).model_dump(mode="json")
    missing_document["author_tests"] = []
    missing_project = await client.post(
        "/api/v1/creator/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "slug": "missing-author-tests",
            "title": "缺少测试作品",
            "document": missing_document,
        },
    )
    assert missing_project.status_code == 201, missing_project.text
    missing_release = await client.post(
        f"/api/v1/creator/projects/{missing_project.json()['id']}/releases",
        headers={"X-CSRF-Token": csrf},
        json={"version": "1.0.0", "visibility": "public"},
    )
    assert missing_release.status_code == 422
    assert "AUTHOR_TESTS_REQUIRED" in missing_release.text


async def test_product_analytics_requires_consent_and_withdrawal_erases_events(client) -> None:
    import sqlalchemy as sa

    import database.session as db_session
    from database.models.platform import ProductEventORM

    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "privacy-player@example.com",
            "password": "correct-horse-privacy",
            "display_name": "隐私测试玩家",
        },
    )
    assert registered.status_code == 201
    user_id = registered.json()["id"]
    csrf = client.cookies.get("ng_csrf")
    privacy = await client.get("/api/v1/settings/privacy")
    assert privacy.status_code == 200
    assert privacy.json()["product_analytics"] is False

    no_consent_project = await client.post(
        "/api/v1/creator/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "slug": "private-before-consent",
            "title": "不应进入事件属性的标题",
            "summary": "不应进入事件属性的简介",
            "template_key": "blank",
        },
    )
    assert no_consent_project.status_code == 201, no_consent_project.text
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        assert (
            int(await session.scalar(sa.select(sa.func.count()).select_from(ProductEventORM)) or 0)
            == 0
        )

    opted_in = await client.put(
        "/api/v1/settings/privacy",
        headers={"X-CSRF-Token": csrf},
        json={"product_analytics": True},
    )
    assert opted_in.status_code == 200
    assert opted_in.json()["product_analytics"] is True
    project = await client.post(
        "/api/v1/creator/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "slug": "private-after-consent",
            "title": "仍然不应进入事件属性的标题",
            "summary": "SECRET-NARRATIVE-TEXT",
            "template_key": "mystery",
        },
    )
    assert project.status_code == 201, project.text
    validated = await client.post(f"/api/v1/creator/projects/{project.json()['id']}/validate")
    assert validated.status_code == 200
    async with maker() as session:
        rows = list(
            (
                await session.execute(
                    sa.select(ProductEventORM).where(ProductEventORM.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert {row.event_name for row in rows} == {
            "analytics_opted_in",
            "project_created",
            "project_validated",
        }
        serialized = repr([row.event_properties for row in rows])
        assert "SECRET-NARRATIVE-TEXT" not in serialized
        assert "仍然不应进入事件属性的标题" not in serialized

    opted_out = await client.put(
        "/api/v1/settings/privacy",
        headers={"X-CSRF-Token": csrf},
        json={"product_analytics": False},
    )
    assert opted_out.status_code == 200
    assert opted_out.json()["product_analytics"] is False
    async with maker() as session:
        remaining = int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(ProductEventORM)
                .where(ProductEventORM.user_id == user_id)
            )
            or 0
        )
        assert remaining == 0


async def test_due_account_worker_scrubs_identity_and_private_access(client) -> None:
    from datetime import UTC, datetime, timedelta

    import database.session as db_session
    from apps.worker.tasks import purge_due_accounts
    from database.models.platform import UserORM
    from engine.core.config import Settings

    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "delete-me@example.com",
            "password": "correct-horse-delete",
            "display_name": "待删除玩家",
        },
    )
    user_id = registered.json()["id"]
    csrf = client.cookies.get("ng_csrf")
    scheduled = await client.delete("/api/v1/settings/account", headers={"X-CSRF-Token": csrf})
    assert scheduled.status_code == 202
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        user = await session.get(UserORM, user_id)
        assert user is not None
        user.delete_after = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert await purge_due_accounts(Settings(require_verified_email=False)) == 1
    async with maker() as session:
        user = await session.get(UserORM, user_id)
        assert user is not None
        assert user.status == "deleted"
        assert user.email == f"deleted-{user_id}@invalid.local"
        assert user.display_name == ""
        assert user.platform_quota_monthly == 0


async def test_async_personal_export_excludes_secrets_and_is_owner_only(client) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "export-owner@example.com",
            "password": "correct-horse-export",
            "display_name": "导出玩家",
        },
    )
    assert registered.status_code == 201
    csrf = client.cookies.get("ng_csrf")
    created = await client.post("/api/v1/settings/data-exports", headers={"X-CSRF-Token": csrf})
    assert created.status_code == 202, created.text
    assert created.json()["status"] == "ready"
    export_id = created.json()["id"]
    downloaded = await client.get(created.json()["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.headers["cache-control"] == "private, no-store"
    document = downloaded.json()
    assert document["account"]["email"] == "export-owner@example.com"
    serialized = downloaded.text
    assert "password_hash" not in serialized
    assert "encrypted_secret" not in serialized
    assert "turn_traces" not in serialized
    assert all("payload" not in save for save in document["saves"])
    assert document["account"]["product_analytics"] is False
    assert document["product_events"] == []

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "export-other@example.com",
            "password": "correct-horse-other",
            "display_name": "其他玩家",
        },
    )
    assert other.status_code == 201
    assert (await client.get(f"/api/v1/settings/data-exports/{export_id}")).status_code == 404


async def test_creator_schema_is_machine_readable(client) -> None:
    response = await client.get("/api/v1/creator/content-pack-schema")
    assert response.status_code == 200
    schema = response.json()
    assert schema["title"] == "ContentPackageV2"
    assert "ContentManifestV2" in schema["$defs"]


async def test_unlisted_release_invitation_is_non_enumerable_and_playable(client) -> None:
    from engine.contentpack.legacy_v2 import project_v1_as_v2
    from engine.contentpack.pack import load_content_pack
    from engine.core.config import get_settings

    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "invite-creator@example.com",
            "password": "correct-horse-invite",
            "display_name": "邀请创作者",
        },
    )
    assert registered.status_code == 201
    document = project_v1_as_v2(
        load_content_pack(get_settings().content_path, "campus_romance_v1"),
        slug="unlisted-invitation-test",
    ).model_dump(mode="json")
    csrf = client.cookies.get("ng_csrf")
    project = await client.post(
        "/api/v1/creator/projects",
        headers={"X-CSRF-Token": csrf},
        json={"slug": "unlisted-invitation-test", "title": "邀请测试", "document": document},
    )
    release = await client.post(
        f"/api/v1/creator/projects/{project.json()['id']}/releases",
        headers={"X-CSRF-Token": csrf},
        json={"version": "1.0.0", "visibility": "unlisted"},
    )
    assert release.status_code == 201, release.text
    token = release.json()["share_token"]
    release_id = release.json()["id"]
    assert token and token not in release_id
    assert (await client.get(f"/api/v1/catalog/releases/{release_id}")).status_code == 404
    assert (await client.get("/api/v1/catalog/shared/not-the-token")).status_code == 404
    shared = await client.get(f"/api/v1/catalog/shared/{token}")
    assert shared.status_code == 200 and shared.json()["id"] == release_id
    invited = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "invited-player@example.com",
            "password": "correct-horse-invited",
            "display_name": "受邀玩家",
        },
    )
    assert invited.status_code == 201
    csrf = client.cookies.get("ng_csrf")
    wrong = await client.post(
        "/api/v1/playthroughs",
        headers={"X-CSRF-Token": csrf},
        json={
            "release_id": release_id,
            "share_token": "wrong",
            "name": "林澄",
            "age": 20,
            "gender": "female",
        },
    )
    assert wrong.status_code == 404
    started = await client.post(
        "/api/v1/playthroughs",
        headers={"X-CSRF-Token": csrf},
        json={
            "release_id": release_id,
            "share_token": token,
            "name": "林澄",
            "age": 20,
            "gender": "female",
        },
    )
    assert started.status_code == 201, started.text


async def test_publication_review_appeal_report_and_audit_flow(client) -> None:
    import database.session as db_session
    from database.models.platform import UserRoleORM
    from engine.contentpack.legacy_v2 import project_v1_as_v2
    from engine.contentpack.pack import load_content_pack
    from engine.core.config import get_settings
    from engine.core.ids import new_id

    creator = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "creator-flow@example.com",
            "password": "correct-horse-creator",
            "display_name": "创作者",
        },
    )
    assert creator.status_code == 201, creator.text
    document = project_v1_as_v2(
        load_content_pack(get_settings().content_path, "campus_romance_v1"),
        slug="moderation-flow",
        rating="16+",
        tags=["审核测试"],
    ).model_dump(mode="json")
    document["manifest"]["title"] = "审核闭环测试作品"
    document["manifest"]["version"] = "1.0.0"
    csrf = client.cookies.get("ng_csrf")
    project = await client.post(
        "/api/v1/creator/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "slug": "moderation-flow",
            "title": "审核闭环测试作品",
            "summary": "只存在于隔离测试数据库",
            "locale": "zh-CN",
            "rating": "16+",
            "document": document,
        },
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    release = await client.post(
        f"/api/v1/creator/projects/{project_id}/releases",
        headers={"X-CSRF-Token": csrf},
        json={"version": "1.0.0", "visibility": "public"},
    )
    assert release.status_code == 201, release.text
    release_id = release.json()["id"]
    assert release.json()["status"] == "pending"
    assert (await client.get("/api/v1/creator/reviews")).status_code == 403

    reviewer = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "reviewer-flow@example.com",
            "password": "correct-horse-reviewer",
            "display_name": "审核员",
        },
    )
    assert reviewer.status_code == 201
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        session.add(UserRoleORM(id=new_id(), user_id=reviewer.json()["id"], role="reviewer"))
        await session.commit()
    reviewer_csrf = client.cookies.get("ng_csrf")
    queued = (await client.get("/api/v1/creator/reviews")).json()
    case = next(item for item in queued if item["release_id"] == release_id)
    rejected = await client.post(
        f"/api/v1/creator/reviews/{case['case_id']}",
        headers={"X-CSRF-Token": reviewer_csrf},
        json={"decision": "rejected", "reason": "需要补充内容分级说明"},
    )
    assert rejected.status_code == 200, rejected.text

    assert (
        await client.post(
            "/api/v1/auth/login",
            json={
                "email": "creator-flow@example.com",
                "password": "correct-horse-creator",
            },
        )
    ).status_code == 200
    creator_csrf = client.cookies.get("ng_csrf")
    appealed = await client.post(
        f"/api/v1/creator/projects/{project_id}/releases/{release_id}/appeal",
        headers={"X-CSRF-Token": creator_csrf},
        json={"reason": "已经补充分级依据，并复核了全部敏感内容标签。"},
    )
    assert appealed.status_code == 202, appealed.text

    assert (
        await client.post(
            "/api/v1/auth/login",
            json={
                "email": "reviewer-flow@example.com",
                "password": "correct-horse-reviewer",
            },
        )
    ).status_code == 200
    reviewer_csrf = client.cookies.get("ng_csrf")
    appealed_cases = (await client.get("/api/v1/creator/reviews")).json()
    appeal_case = next(item for item in appealed_cases if item["release_id"] == release_id)
    assert appeal_case["evidence"][0]["kind"] == "appeal"
    approved = await client.post(
        f"/api/v1/creator/reviews/{appeal_case['case_id']}",
        headers={"X-CSRF-Token": reviewer_csrf},
        json={"decision": "approved", "reason": "复核通过，可以公开"},
    )
    assert approved.status_code == 200, approved.text

    reporter = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "reporter-flow@example.com",
            "password": "correct-horse-reporter",
            "display_name": "举报者",
        },
    )
    assert reporter.status_code == 201
    reporter_csrf = client.cookies.get("ng_csrf")
    duplicate_project = await client.post(
        "/api/v1/creator/projects",
        headers={"X-CSRF-Token": reporter_csrf},
        json={
            "slug": "moderation-flow",
            "title": "审核闭环测试作品",
            "summary": "相同规范制品属于另一个创作者",
            "locale": "zh-CN",
            "rating": "16+",
            "document": document,
        },
    )
    assert duplicate_project.status_code == 201, duplicate_project.text
    duplicate_release = await client.post(
        f"/api/v1/creator/projects/{duplicate_project.json()['id']}/releases",
        headers={"X-CSRF-Token": reporter_csrf},
        json={"version": "1.0.0", "visibility": "private"},
    )
    assert duplicate_release.status_code == 201, duplicate_release.text
    assert duplicate_release.json()["checksum"] == release.json()["checksum"]
    report = await client.post(
        f"/api/v1/catalog/releases/{release_id}/reports",
        headers={"X-CSRF-Token": reporter_csrf},
        json={"category": "分级", "details": "请审核某个剧情节拍的分级是否准确"},
    )
    assert report.status_code == 201, report.text

    assert (
        await client.post(
            "/api/v1/auth/login",
            json={
                "email": "reviewer-flow@example.com",
                "password": "correct-horse-reviewer",
            },
        )
    ).status_code == 200
    reviewer_csrf = client.cookies.get("ng_csrf")
    reports = (await client.get("/api/v1/creator/reports")).json()
    queued_report = next(item for item in reports if item["id"] == report.json()["id"])
    takedown = await client.post(
        f"/api/v1/creator/reports/{queued_report['id']}",
        headers={"X-CSRF-Token": reviewer_csrf},
        json={"decision": "takedown", "note": "先下架并交由内容团队复核"},
    )
    assert takedown.status_code == 200, takedown.text
    audit = (await client.get("/api/v1/creator/audit-logs")).json()
    actions = {item["action"] for item in audit}
    assert {
        "release.created",
        "moderation.appealed",
        "moderation.decided",
        "report.decided",
    } <= actions


async def test_v1_registration_playthrough_and_cross_user_isolation(client) -> None:
    first = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "first@example.com",
            "password": "correct-horse-123",
            "display_name": "一号",
        },
    )
    assert first.status_code == 201, first.text
    catalog = await client.get("/api/v1/catalog/releases")
    campus = next(item for item in catalog.json()["items"] if "春日坂" in item["title"])
    csrf = client.cookies.get("ng_csrf")
    started = await client.post(
        "/api/v1/playthroughs",
        headers={"X-CSRF-Token": csrf},
        json={
            "release_id": campus["id"],
            "name": "林夏",
            "age": 20,
            "gender": "female",
            "player_config": {
                "major": "journalism",
                "interests": ["摄影"],
                "personality_tendency": "curious",
                "personal_goal": "完成一篇真正重要的报道",
            },
        },
    )
    assert started.status_code == 201, started.text
    playthrough_id = started.json()["id"]
    state = (await client.get(f"/api/v1/playthroughs/{playthrough_id}/state")).json()
    assert state["player"]["properties"]["major"] == "journalism"
    assert state["player"]["properties"]["interests"] == ["摄影"]
    assert state["player"]["resources"]["energy"]["current"] == 80
    settings = (await client.get(f"/api/v1/playthroughs/{playthrough_id}/settings")).json()
    assert settings["narrative_length"] == "standard"
    assert settings["narrative_max_chars"] == 1600
    changed = await client.put(
        f"/api/v1/playthroughs/{playthrough_id}/settings",
        headers={"X-CSRF-Token": csrf},
        json={"narrative_length": "detailed"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["narrative_max_chars"] == 2400

    second = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "second@example.com",
            "password": "correct-horse-456",
            "display_name": "二号",
        },
    )
    assert second.status_code == 201, second.text
    denied = await client.get(f"/api/v1/playthroughs/{playthrough_id}/state")
    assert denied.status_code == 404
    assert denied.headers["content-type"].startswith("application/problem+json")
    assert (await client.get(f"/api/v1/playthroughs/{playthrough_id}/recap")).status_code == 404
    second_csrf = client.cookies.get("ng_csrf")
    denied_delete = await client.delete(
        f"/api/v1/playthroughs/{playthrough_id}",
        headers={"X-CSRF-Token": second_csrf},
    )
    assert denied_delete.status_code == 404

    logged_back_in = await client.post(
        "/api/v1/auth/login",
        json={"email": "first@example.com", "password": "correct-horse-123"},
    )
    assert logged_back_in.status_code == 200
    first_csrf = client.cookies.get("ng_csrf")
    deleted = await client.delete(
        f"/api/v1/playthroughs/{playthrough_id}",
        headers={"X-CSRF-Token": first_csrf},
    )
    assert deleted.status_code == 204
    assert playthrough_id not in {
        item["id"] for item in (await client.get("/api/v1/playthroughs")).json()
    }
    assert (await client.get(f"/api/v1/playthroughs/{playthrough_id}/state")).status_code == 404


async def test_catalog_filters_tags_and_popularity_sort(client) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "catalog-reader@example.com",
            "password": "correct-horse-catalog",
            "display_name": "目录读者",
        },
    )
    assert registered.status_code == 201
    initial = (await client.get("/api/v1/catalog/releases")).json()["items"]
    campus = next(item for item in initial if "春日坂" in item["title"])
    assert campus["tags"]

    tag = campus["tags"][0]
    tagged = (await client.get("/api/v1/catalog/releases", params={"tag": tag})).json()
    assert tagged["items"]
    assert all(tag in item["tags"] for item in tagged["items"])

    filtered = (
        await client.get(
            "/api/v1/catalog/releases",
            params={"locale": campus["locale"], "rating": campus["rating"]},
        )
    ).json()["items"]
    assert campus["id"] in {item["id"] for item in filtered}
    assert all(
        item["locale"] == campus["locale"] and item["rating"] == campus["rating"]
        for item in filtered
    )

    csrf = client.cookies.get("ng_csrf")
    started = await client.post(
        "/api/v1/playthroughs",
        headers={"X-CSRF-Token": csrf},
        json={"release_id": campus["id"], "name": "目录测试", "age": 20, "gender": "female"},
    )
    assert started.status_code == 201, started.text
    popular = (await client.get("/api/v1/catalog/releases", params={"sort": "popular"})).json()[
        "items"
    ]
    assert popular[0]["id"] == campus["id"]
    assert popular[0]["play_count"] == 1


async def test_concurrent_actions_for_one_playthrough_are_serialized(client) -> None:
    import sqlalchemy as sa

    import database.session as db_session
    from database.models.platform import ProductEventORM

    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "serialized-actions@example.com",
            "password": "correct-horse-serialized",
            "display_name": "串行行动",
        },
    )
    assert registered.status_code == 201
    csrf = client.cookies.get("ng_csrf")
    consent = await client.put(
        "/api/v1/settings/privacy",
        headers={"X-CSRF-Token": csrf},
        json={"product_analytics": True},
    )
    assert consent.status_code == 200
    releases = (await client.get("/api/v1/catalog/releases")).json()["items"]
    campus = next(item for item in releases if "春日坂" in item["title"])
    started = await client.post(
        "/api/v1/playthroughs",
        headers={"X-CSRF-Token": csrf},
        json={"release_id": campus["id"], "name": "林夏", "age": 20, "gender": "female"},
    )
    assert started.status_code == 201
    playthrough_id = started.json()["id"]

    async def act(index: int):
        return await client.post(
            f"/api/v1/playthroughs/{playthrough_id}/actions",
            headers={"X-CSRF-Token": csrf},
            json={
                "text": "观察周围",
                "idempotency_key": f"serialized-action-{index}",
            },
        )

    first, second = await asyncio.gather(act(1), act(2))
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["turn_id"] != second.json()["turn_id"]
    replay = await act(1)
    assert replay.status_code == 200
    assert replay.json()["turn_id"] == first.json()["turn_id"]
    recap = await client.get(f"/api/v1/playthroughs/{playthrough_id}/recap")
    assert recap.status_code == 200, recap.text
    assert recap.json()["turn_number"] == 2
    assert recap.json()["last_action"] == "观察周围"
    assert recap.json()["recent"]
    assert all(len(item["text"]) <= 261 for item in recap.json()["recent"])
    assert "debug" not in recap.text and "trace" not in recap.text
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        events = list(
            (
                await session.execute(
                    sa.select(ProductEventORM).where(
                        ProductEventORM.playthrough_id == playthrough_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert [row.event_name for row in events].count("playthrough_started") == 1
    assert [row.event_name for row in events].count("action_completed") == 2
    assert all("text" not in row.event_properties for row in events)


async def test_playthrough_consent_ending_and_save_rewind(client) -> None:
    import sqlalchemy as sa

    import database.session as db_session
    from database.models.orm import EventORM, WorldORM
    from database.models.platform import PlaythroughORM

    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "ending-player@example.com",
            "password": "correct-horse-ending",
            "display_name": "结局测试者",
        },
    )
    assert registered.status_code == 201
    csrf = client.cookies.get("ng_csrf")
    catalog = (await client.get("/api/v1/catalog/releases")).json()["items"]
    campus = next(item for item in catalog if "春日坂" in item["title"])
    started = await client.post(
        "/api/v1/playthroughs",
        headers={"X-CSRF-Token": csrf},
        json={"release_id": campus["id"], "name": "林夏", "age": 20, "gender": "female"},
    )
    assert started.status_code == 201, started.text
    playthrough_id = started.json()["id"]
    saved = await client.post(
        f"/api/v1/playthroughs/{playthrough_id}/saves",
        headers={"X-CSRF-Token": csrf},
        json={"name": "学期开始"},
    )
    assert saved.status_code == 201

    rejected = await client.put(
        f"/api/v1/playthroughs/{playthrough_id}/relationships/haruto/consent",
        headers={"X-CSRF-Token": csrf},
        json={"decision": "rejected"},
    )
    assert rejected.status_code == 200, rejected.text
    ending_status = await client.get(f"/api/v1/playthroughs/{playthrough_id}/endings")
    assert ending_status.status_code == 200
    assert ending_status.json()["consent"]["haruto"] == "rejected"
    assert ending_status.json()["hidden_count"] == 8

    maker = db_session.get_sessionmaker()
    async with maker() as session:
        play = await session.get(PlaythroughORM, playthrough_id)
        assert play is not None and play.world_id
        world = await session.get(WorldORM, play.world_id)
        assert world is not None
        world.current_minute = 120_960
        await session.commit()

    ending_status = (await client.get(f"/api/v1/playthroughs/{playthrough_id}/endings")).json()
    independent = next(
        item for item in ending_status["endings"] if item["key"] == "independent_growth"
    )
    assert independent["available"] is True
    completed = await client.post(
        f"/api/v1/playthroughs/{playthrough_id}/ending",
        headers={"X-CSRF-Token": csrf},
        json={"ending_key": "independent_growth"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["title"] == "未完通信"
    assert (await client.get(f"/api/v1/playthroughs/{playthrough_id}/state")).json()["playthrough"][
        "status"
    ] == "completed"
    blocked_action = await client.post(
        f"/api/v1/playthroughs/{playthrough_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json={"text": "继续", "idempotency_key": "after-ending"},
    )
    assert blocked_action.status_code == 409
    history = (await client.get(f"/api/v1/playthroughs/{playthrough_id}/history")).json()
    assert any("属于自己的下一页" in chapter["text"] for chapter in history["chapters"])
    async with maker() as session:
        ending_events = (
            (
                await session.execute(
                    sa.select(EventORM).where(
                        EventORM.world_id == play.world_id,
                        EventORM.event_type == "PLAYTHROUGH_ENDING_SELECTED",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(ending_events) == 1

    rewound = await client.post(
        f"/api/v1/playthroughs/{playthrough_id}/saves/{saved.json()['id']}/load",
        headers={"X-CSRF-Token": csrf},
    )
    assert rewound.status_code == 200, rewound.text
    state = (await client.get(f"/api/v1/playthroughs/{playthrough_id}/state")).json()
    assert state["playthrough"]["status"] == "active"
    assert state["playthrough"]["ending_key"] is None


async def test_v1_history_saves_and_credentials_are_owner_scoped(client, monkeypatch) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@example.com",
            "password": "correct-horse-789",
            "display_name": "存档者",
        },
    )
    assert registered.status_code == 201
    csrf = client.cookies.get("ng_csrf")
    catalog = (await client.get("/api/v1/catalog/releases")).json()["items"]
    campus = next(item for item in catalog if "春日坂" in item["title"])
    started = await client.post(
        "/api/v1/playthroughs",
        headers={"X-CSRF-Token": csrf},
        json={"release_id": campus["id"], "name": "林夏", "age": 20, "gender": "female"},
    )
    assert started.status_code == 201, started.text
    playthrough_id = started.json()["id"]
    acted = await client.post(
        f"/api/v1/playthroughs/{playthrough_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json={"text": "我环顾四周", "idempotency_key": "owner-history-1"},
    )
    assert acted.status_code == 200, acted.text
    acted_state = (await client.get(f"/api/v1/playthroughs/{playthrough_id}/state")).json()
    assert acted_state["player"]["resources"]["energy"]["current"] == 76
    history = await client.get(f"/api/v1/playthroughs/{playthrough_id}/history")
    assert history.status_code == 200
    assert any(item["input"] == "我环顾四周" for item in history.json()["chapters"])

    saved = await client.post(
        f"/api/v1/playthroughs/{playthrough_id}/saves",
        headers={"X-CSRF-Token": csrf},
        json={"name": "礼堂之前"},
    )
    assert saved.status_code == 201, saved.text
    save_id = saved.json()["id"]
    credential = await client.put(
        "/api/v1/settings/llm-credentials",
        headers={"X-CSRF-Token": csrf},
        json={"provider": "openai", "model": "gpt-test", "secret": "sk-never-echo-this"},
    )
    assert credential.status_code == 200
    assert "never-echo" not in credential.text
    import apps.api.routers.settings as settings_router
    from engine.llm.providers import ScriptedProvider

    monkeypatch.setattr(
        settings_router, "build_provider", lambda _settings: ScriptedProvider(default="OK")
    )
    tested = await client.post(
        "/api/v1/settings/llm-credentials/openai/test",
        headers={"X-CSRF-Token": csrf},
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["status"] == "ok"
    assert "never-echo" not in tested.text

    compatible = await client.put(
        "/api/v1/settings/llm-credentials",
        headers={"X-CSRF-Token": csrf},
        json={
            "provider": "compatible",
            "model": "deepseek-chat",
            "secret": "sk-compatible-never-echo",
            "base_url": "https://api.deepseek.com",
        },
    )
    assert compatible.status_code == 200, compatible.text
    assert compatible.json()["base_url"] == "https://api.deepseek.com"
    assert "compatible-never-echo" not in compatible.text
    compatible_test = await client.post(
        "/api/v1/settings/llm-credentials/compatible/test",
        headers={"X-CSRF-Token": csrf},
    )
    assert compatible_test.status_code == 200, compatible_test.text

    private_endpoint = await client.put(
        "/api/v1/settings/llm-credentials",
        headers={"X-CSRF-Token": csrf},
        json={
            "provider": "compatible",
            "model": "blocked",
            "secret": "sk-private-endpoint",
            "base_url": "https://127.0.0.1/v1",
        },
    )
    assert private_endpoint.status_code == 422
    assert "sk-private-endpoint" not in private_endpoint.text

    second = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "intruder@example.com",
            "password": "correct-horse-987",
            "display_name": "越权者",
        },
    )
    assert second.status_code == 201
    second_csrf = client.cookies.get("ng_csrf")
    assert (await client.get("/api/v1/settings/llm-credentials")).json() == []
    denied = await client.post(
        f"/api/v1/playthroughs/{playthrough_id}/saves/{save_id}/load",
        headers={"X-CSRF-Token": second_csrf},
    )
    assert denied.status_code == 404


async def test_start_game_then_act(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-1"}
    )
    assert started.status_code == 200, started.text
    payload = started.json()
    session_id = payload["session_id"]
    assert payload["opening"]
    assert payload["state"]["location"]["name"]

    acted = await client.post(
        f"/api/game/{session_id}/action", json={"text": "我环顾四周", "debug": True}
    )
    assert acted.status_code == 200, acted.text
    turn = acted.json()
    assert turn["narrative"]
    assert turn["turn_id"]
    assert turn["debug"]["intent"]["action_type"] == "OBSERVE"

    state = await client.get(f"/api/game/{session_id}/state")
    assert state.status_code == 200
    assert state.json()["session"]["turn_number"] == 1

    history = await client.get(f"/api/game/{session_id}/history")
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["player_input"] == "我环顾四周"


async def test_start_requires_an_adult_and_selects_the_gendered_lead(client) -> None:
    underage = await client.post(
        "/api/game/start",
        json={"player_name": "未成年", "gender": "male", "age": 17},
    )
    assert underage.status_code == 422

    started = await client.post(
        "/api/game/start",
        json={
            "player_name": "云枝",
            "gender": "female",
            "age": 23,
            "world_seed": "female-lead-api",
            "narrative_max_chars": 1200,
        },
    )
    assert started.status_code == 200, started.text
    assert any(
        character["name"] == "赵无极" for character in started.json()["state"]["present_characters"]
    )
    relationships = (
        await client.get(f"/api/game/{started.json()['session_id']}/relationships")
    ).json()
    lead = next(row for row in relationships if row["with_key"] == "zhao_wuji")
    assert "co_protagonist" in lead["tags"]


async def test_api_validates_narrative_length_limits(client) -> None:
    too_short = await client.post(
        "/api/game/start",
        json={"player_name": "沈砚", "narrative_max_chars": 399},
    )
    assert too_short.status_code == 422

    started = await client.post(
        "/api/game/start",
        json={"player_name": "沈砚", "world_seed": "length-api"},
    )
    session_id = started.json()["session_id"]
    too_long = await client.post(
        f"/api/game/{session_id}/action",
        json={"text": "继续", "narrative_max_chars": 4001},
    )
    assert too_long.status_code == 422


async def test_action_response_shape_matches_the_contract(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-2"}
    )
    session_id = started.json()["session_id"]
    turn = (
        await client.post(f"/api/game/{session_id}/action", json={"text": "我打坐修炼一个时辰"})
    ).json()
    for key in ("narrative", "state_changes", "visible_updates", "choices"):
        assert key in turn
    assert isinstance(turn["choices"], list)
    assert turn["state_changes"]["world_minute"][1] > turn["state_changes"]["world_minute"][0]


async def test_idempotency_header_is_honoured(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-3"}
    )
    session_id = started.json()["session_id"]
    headers = {"Idempotency-Key": "abc-123"}
    first = await client.post(
        f"/api/game/{session_id}/action", json={"text": "我打坐修炼一个时辰"}, headers=headers
    )
    second = await client.post(
        f"/api/game/{session_id}/action", json={"text": "我打坐修炼一个时辰"}, headers=headers
    )
    assert first.json()["turn_id"] == second.json()["turn_id"]

    state = await client.get(f"/api/game/{session_id}/state")
    assert state.json()["session"]["turn_number"] == 1


async def test_sse_stream_settles_the_world_before_narrating(client) -> None:
    """Prompt section 49: the world is settled before narration starts.

    The prose is now streamed as it is written, so "state first" is no longer
    the observable form of this - the final state carries the chapter's beat
    and cannot exist before the chapter does. What still must hold is that
    every committed step is announced before the first character of prose.
    """
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-4"}
    )
    session_id = started.json()["session_id"]
    async with client.stream(
        "POST", f"/api/game/{session_id}/action/stream", json={"text": "我环顾四周"}
    ) as response:
        assert response.status_code == 200
        body = ""
        async for chunk in response.aiter_text():
            body += chunk

    assert "event: narrative" in body
    if "event: progress" in body:
        assert body.rindex("event: progress") < body.index("event: narrative")
    # State always precedes the terminator, and the terminator is last.
    assert body.index("event: state") < body.index("event: done")
    assert body.rstrip().endswith("}") and "event: done" in body


async def test_v1_sse_disables_proxy_transforms(client) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "stream-reader@example.com",
            "password": "correct-horse-stream-reader",
            "display_name": "流式读者",
        },
    )
    assert registered.status_code == 201
    csrf = client.cookies.get("ng_csrf")
    releases = (await client.get("/api/v1/catalog/releases")).json()["items"]
    campus = next(item for item in releases if "春日坂" in item["title"])
    started = await client.post(
        "/api/v1/playthroughs",
        headers={"X-CSRF-Token": csrf},
        json={"release_id": campus["id"], "name": "林夏", "age": 20, "gender": "female"},
    )
    assert started.status_code == 201
    playthrough_id = started.json()["id"]

    async with client.stream(
        "POST",
        f"/api/v1/playthroughs/{playthrough_id}/actions/stream",
        headers={"X-CSRF-Token": csrf},
        json={"text": "我看看桌上的资料", "idempotency_key": "stream-reader-turn"},
    ) as response:
        body = "".join([chunk async for chunk in response.aiter_text()])

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: state" in body
    assert "event: done" in body


async def test_sse_idempotency_header_replays_without_advancing_twice(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "sse-idem"}
    )
    session_id = started.json()["session_id"]
    headers = {"Idempotency-Key": "sse-header-key"}
    first = await client.post(
        f"/api/game/{session_id}/action/stream",
        json={"text": "我环顾四周"},
        headers=headers,
    )
    second = await client.post(
        f"/api/game/{session_id}/action/stream",
        json={"text": "我环顾四周"},
        headers=headers,
    )
    assert first.status_code == second.status_code == 200
    state = await client.get(f"/api/game/{session_id}/state")
    assert state.json()["session"]["turn_number"] == 1


async def test_inventory_relationships_and_quests(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-5"}
    )
    session_id = started.json()["session_id"]

    inventory = (await client.get(f"/api/game/{session_id}/inventory")).json()
    assert inventory and all("name" in row for row in inventory)

    quests = (await client.get(f"/api/game/{session_id}/quests")).json()
    assert any(q["status"] == "offered" for q in quests)

    relationships = (await client.get(f"/api/game/{session_id}/relationships")).json()
    assert isinstance(relationships, list)


async def test_debug_trace_endpoint(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-6"}
    )
    session_id = started.json()["session_id"]
    turn = (await client.post(f"/api/game/{session_id}/action", json={"text": "我环顾四周"})).json()

    trace = await client.get(f"/api/debug/turn/{turn['turn_id']}")
    assert trace.status_code == 200
    body = trace.json()
    assert body["stage_timings"]
    assert "intent" in body and "rule_result" in body
    assert "rng_traces" in body


async def test_world_inspector(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-7"}
    )
    world_id = started.json()["world_id"]

    inspector = await client.get(f"/api/admin/world/{world_id}/inspector")
    assert inspector.status_code == 200
    body = inspector.json()
    assert body["world"]["character_count"] > 10
    assert body["factions"]
    assert body["plot_threads"]
    assert body["director_events"]
    assert {event["status"] for event in body["director_events"]} == {"SCHEDULED"}
    assert "band" in body["tension"]


async def test_inspector_knowledge_view_shows_beliefs_not_truth(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-8"}
    )
    world_id = started.json()["world_id"]
    inspector = (await client.get(f"/api/admin/world/{world_id}/inspector")).json()
    npc = next(c for c in inspector["characters"] if c["character_type"] == "MAJOR_NPC")

    knowledge = await client.get(f"/api/admin/character/{npc['id']}/knowledge")
    assert knowledge.status_code == 200
    rows = knowledge.json()
    assert all("state" in r and "confidence" in r for r in rows)
    assert all("truth_value" not in r for r in rows)


async def test_unknown_session_is_a_404(client) -> None:
    response = await client.get("/api/game/does-not-exist/state")
    assert response.status_code == 404


async def test_worlds_and_characters_endpoints(client) -> None:
    created = await client.post("/api/worlds", json={"world_seed": "api-test-9"})
    assert created.status_code == 201, created.text
    world = created.json()
    assert world["character_count"] > 10
    assert world["location_count"] > 5

    fetched = await client.get(f"/api/worlds/{world['id']}")
    assert fetched.status_code == 200

    inspector = (await client.get(f"/api/admin/world/{world['id']}/inspector")).json()
    npc_id = inspector["characters"][0]["id"]

    character = await client.get(f"/api/characters/{npc_id}")
    assert character.status_code == 200
    assert character.json()["realm_display"]

    relationships = await client.get(f"/api/characters/{npc_id}/relationships")
    assert relationships.status_code == 200

    memories = await client.get(f"/api/characters/{npc_id}/memories")
    assert memories.status_code == 200

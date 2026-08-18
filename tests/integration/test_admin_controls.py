"""Strong administrator powers, and the limits that make them safe to have.

Every test here is really about a boundary: a bulk change that could hit the
whole platform, an account that can be erased, and reading a player's private
writing. The powers are the point; so is being unable to use them by accident.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def admin_session(client, email: str, password: str) -> str:
    """Register an account, make it an administrator, and pass MFA step-up."""
    import time

    import database.session as db_session
    from apps.api.security import _totp
    from database.models.platform import UserRoleORM
    from engine.core.ids import new_id

    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": "管理员"},
    )
    assert registered.status_code == 201, registered.text
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        session.add(UserRoleORM(id=new_id(), user_id=registered.json()["id"], role="admin"))
        await session.commit()
    csrf = client.cookies.get("ng_csrf")
    enrollment = await client.post(
        "/api/v1/auth/mfa/enroll",
        headers={"X-CSRF-Token": csrf},
        json={"password": password},
    )
    assert enrollment.status_code == 200, enrollment.text
    confirmation = await client.post(
        "/api/v1/auth/mfa/confirm",
        headers={"X-CSRF-Token": csrf},
        json={"code": _totp(enrollment.json()["secret"], int(time.time() // 30))},
    )
    assert confirmation.status_code == 200, confirmation.text
    return csrf


async def register(client, email: str, name: str = "玩家") -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-player", "display_name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_bulk_quota_requires_the_administrator_to_have_read_the_count(client) -> None:
    for index in range(3):
        await register(client, f"bulk-player-{index}@example.com", f"玩家{index}")
    csrf = await admin_session(client, "bulk-admin@example.com", "correct-horse-admin")

    preview = await client.get("/api/v1/admin/users/quota/bulk/preview?scope=all")
    assert preview.status_code == 200, preview.text
    matched = preview.json()["matched"]
    assert matched >= 4

    # A stale count is refused rather than quietly applied to a different set.
    stale = await client.post(
        "/api/v1/admin/users/quota/bulk",
        headers={"X-CSRF-Token": csrf},
        json={"monthly_tokens": 500_000, "reason": "开放公测额度", "expect_users": matched - 1},
    )
    assert stale.status_code == 409

    applied = await client.post(
        "/api/v1/admin/users/quota/bulk",
        headers={"X-CSRF-Token": csrf},
        json={"monthly_tokens": 500_000, "reason": "开放公测额度", "expect_users": matched},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["affected"] == matched

    listing = await client.get("/api/v1/admin/users?query=bulk-player")
    assert {item["monthly_quota"] for item in listing.json()["items"]} == {500_000}


async def test_bulk_quota_can_target_a_single_role(client) -> None:
    import database.session as db_session
    from database.models.platform import UserRoleORM
    from engine.core.ids import new_id

    creator_id = await register(client, "role-creator@example.com", "作者")
    await register(client, "role-player@example.com", "玩家")
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        session.add(UserRoleORM(id=new_id(), user_id=creator_id, role="creator"))
        await session.commit()
    csrf = await admin_session(client, "role-admin@example.com", "correct-horse-admin")

    preview = await client.get("/api/v1/admin/users/quota/bulk/preview?scope=role&role=creator")
    assert preview.json()["matched"] == 1

    applied = await client.post(
        "/api/v1/admin/users/quota/bulk",
        headers={"X-CSRF-Token": csrf},
        json={
            "monthly_tokens": 900_000,
            "reason": "作者额度上调",
            "scope": "role",
            "role": "creator",
            "expect_users": 1,
        },
    )
    assert applied.status_code == 200, applied.text

    listing = await client.get("/api/v1/admin/users?query=role-")
    quotas = {item["email"]: item["monthly_quota"] for item in listing.json()["items"]}
    assert quotas["role-creator@example.com"] == 900_000
    assert quotas["role-player@example.com"] != 900_000


async def test_suspending_an_account_blocks_sign_in(client) -> None:
    victim_id = await register(client, "suspend-me@example.com", "被封玩家")
    csrf = await admin_session(client, "suspend-admin@example.com", "correct-horse-admin")

    suspended = await client.post(
        f"/api/v1/admin/users/{victim_id}/suspend",
        headers={"X-CSRF-Token": csrf},
        json={"suspended": True, "reason": "违规内容举报成立"},
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"

    blocked = await client.post(
        "/api/v1/auth/login",
        json={"email": "suspend-me@example.com", "password": "correct-horse-player"},
    )
    assert blocked.status_code == 403

    reinstated = await client.post(
        f"/api/v1/admin/users/{victim_id}/suspend",
        headers={"X-CSRF-Token": csrf},
        json={"suspended": False, "reason": "申诉成立"},
    )
    assert reinstated.json()["status"] == "active"
    allowed = await client.post(
        "/api/v1/auth/login",
        json={"email": "suspend-me@example.com", "password": "correct-horse-player"},
    )
    assert allowed.status_code == 200


async def test_an_administrator_cannot_suspend_or_delete_themselves(client) -> None:
    csrf = await admin_session(client, "self-admin@example.com", "correct-horse-admin")
    admin_id = (await client.get("/api/v1/auth/me")).json()["id"]

    suspend = await client.post(
        f"/api/v1/admin/users/{admin_id}/suspend",
        headers={"X-CSRF-Token": csrf},
        json={"suspended": True, "reason": "手滑点错"},
    )
    assert suspend.status_code == 409

    delete = await client.post(
        f"/api/v1/admin/users/{admin_id}/delete",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "手滑点错", "confirm_email": "self-admin@example.com"},
    )
    assert delete.status_code == 409


async def test_deleting_an_account_requires_typing_its_address(client) -> None:
    victim_id = await register(client, "delete-me@example.com", "待删除")
    csrf = await admin_session(client, "delete-admin@example.com", "correct-horse-admin")

    mistyped = await client.post(
        f"/api/v1/admin/users/{victim_id}/delete",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "用户申请注销", "confirm_email": "delete-you@example.com"},
    )
    assert mistyped.status_code == 409

    confirmed = await client.post(
        f"/api/v1/admin/users/{victim_id}/delete",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "用户申请注销", "confirm_email": "delete-me@example.com"},
    )
    assert confirmed.status_code == 200, confirmed.text

    # The address is gone and the account is dead; the row survives as a
    # pseudonym because audit entries and other people's playthroughs still
    # reference it.
    assert (await client.get("/api/v1/admin/users?query=delete-me@")).json()["items"] == []
    scrubbed = (await client.get(f"/api/v1/admin/users?query={victim_id}")).json()["items"]
    assert [item["status"] for item in scrubbed] == ["deleted"]
    assert scrubbed[0]["email"] == f"deleted-{victim_id}@invalid.local"
    assert scrubbed[0]["display_name"] == ""

    blocked = await client.post(
        "/api/v1/auth/login",
        json={"email": "delete-me@example.com", "password": "correct-horse-player"},
    )
    assert blocked.status_code == 401


async def test_revoking_sessions_signs_an_account_out_without_blocking_it(client) -> None:
    victim_id = await register(client, "kick-me@example.com", "被踢下线")
    csrf = await admin_session(client, "kick-admin@example.com", "correct-horse-admin")

    revoked = await client.post(
        f"/api/v1/admin/users/{victim_id}/revoke-sessions",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "疑似账号泄露"},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked"] >= 1

    # Still allowed back in - this is a sign-out, not a ban.
    allowed = await client.post(
        "/api/v1/auth/login",
        json={"email": "kick-me@example.com", "password": "correct-horse-player"},
    )
    assert allowed.status_code == 200


async def test_the_default_quota_applies_to_accounts_created_afterwards(client) -> None:
    csrf = await admin_session(client, "default-admin@example.com", "correct-horse-admin")

    changed = await client.put(
        "/api/v1/admin/settings/default-quota",
        headers={"X-CSRF-Token": csrf},
        json={"monthly_tokens": 42_000, "reason": "收紧新用户额度"},
    )
    assert changed.status_code == 200, changed.text

    # Registering signs the client in as the new account, so the quota is read
    # back from the database rather than through the administrator API.
    import sqlalchemy as sa

    import database.session as db_session
    from database.models.platform import UserORM

    await register(client, "after-default@example.com", "新玩家")
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        quota = await session.scalar(
            sa.select(UserORM.platform_quota_monthly).where(
                UserORM.email == "after-default@example.com"
            )
        )
    assert quota == 42_000


async def test_an_announcement_reaches_players_and_can_be_withdrawn(client) -> None:
    assert (await client.get("/api/v1/auth/announcement")).json()["active"] is False
    csrf = await admin_session(client, "notice-admin@example.com", "correct-horse-admin")

    await client.put(
        "/api/v1/admin/settings/announcement",
        headers={"X-CSRF-Token": csrf},
        json={
            "message": "今晚 23:00 维护，约 20 分钟。",
            "level": "maintenance",
            "active": True,
            "reason": "计划内维护",
        },
    )
    live = (await client.get("/api/v1/auth/announcement")).json()
    assert live["active"] is True
    assert live["level"] == "maintenance"

    await client.put(
        "/api/v1/admin/settings/announcement",
        headers={"X-CSRF-Token": csrf},
        json={"message": "", "level": "info", "active": False, "reason": "维护结束"},
    )
    assert (await client.get("/api/v1/auth/announcement")).json()["active"] is False


async def test_an_empty_announcement_can_never_be_active(client) -> None:
    csrf = await admin_session(client, "blank-admin@example.com", "correct-horse-admin")

    response = await client.put(
        "/api/v1/admin/settings/announcement",
        headers={"X-CSRF-Token": csrf},
        json={"message": "   ", "level": "warning", "active": True, "reason": "空公告"},
    )

    assert response.json()["active"] is False


async def test_inspecting_a_player_is_read_only_and_visible_to_that_player(client) -> None:
    player_id = await register(client, "inspect-me@example.com", "被查看的玩家")
    csrf = await admin_session(client, "inspect-admin@example.com", "correct-horse-admin")

    looked = await client.post(
        f"/api/v1/admin/users/{player_id}/inspect",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "玩家报告存档打不开"},
    )
    assert looked.status_code == 200, looked.text
    assert looked.json()["read_only"] is True
    assert looked.json()["user"]["id"] == player_id

    # Being able to find out is the part that makes the power acceptable.
    signed_in = await client.post(
        "/api/v1/auth/login",
        json={"email": "inspect-me@example.com", "password": "correct-horse-player"},
    )
    assert signed_in.status_code == 200
    log = await client.get("/api/v1/settings/privacy/access-log")
    assert log.status_code == 200, log.text
    assert [entry["reason"] for entry in log.json()["entries"]] == ["玩家报告存档打不开"]


async def test_strong_actions_are_refused_without_the_admin_role(client) -> None:
    victim_id = await register(client, "not-admin-target@example.com", "目标")
    await register(client, "not-admin@example.com", "普通玩家")
    csrf = client.cookies.get("ng_csrf")

    attempts = [
        (f"/api/v1/admin/users/{victim_id}/suspend", {"suspended": True, "reason": "越权尝试"}),
        (f"/api/v1/admin/users/{victim_id}/inspect", {"reason": "越权尝试"}),
        (f"/api/v1/admin/users/{victim_id}/revoke-sessions", {"reason": "越权尝试"}),
        (
            "/api/v1/admin/users/quota/bulk",
            {"monthly_tokens": 0, "reason": "越权尝试", "expect_users": 1},
        ),
    ]
    for path, payload in attempts:
        response = await client.post(path, headers={"X-CSRF-Token": csrf}, json=payload)
        assert response.status_code == 403, (path, response.text)

    settings_attempt = await client.put(
        "/api/v1/admin/settings/announcement",
        headers={"X-CSRF-Token": csrf},
        json={"message": "越权公告", "level": "info", "active": True, "reason": "越权尝试"},
    )
    assert settings_attempt.status_code == 403

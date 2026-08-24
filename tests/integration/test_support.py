"""Support-case API: player privacy, queue operations and durable replies."""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.integration


async def _register(client, email: str, password: str, name: str) -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _admin_session(client, email: str, password: str) -> tuple[str, str]:
    import database.session as db_session
    from apps.api.security import _totp
    from database.models.platform import UserRoleORM
    from engine.core.ids import new_id

    admin_id = await _register(client, email, password, "Support operator")
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        session.add(UserRoleORM(id=new_id(), user_id=admin_id, role="admin"))
        await session.commit()
    csrf = client.cookies.get("ng_csrf")
    enrollment = await client.post(
        "/api/v1/auth/mfa/enroll",
        headers={"X-CSRF-Token": csrf},
        json={"password": password},
    )
    assert enrollment.status_code == 200, enrollment.text
    confirmed = await client.post(
        "/api/v1/auth/mfa/confirm",
        headers={"X-CSRF-Token": csrf},
        json={"code": _totp(enrollment.json()["secret"], int(time.time() // 30))},
    )
    assert confirmed.status_code == 200, confirmed.text
    return admin_id, csrf


async def test_support_case_keeps_player_messages_private_and_audits_operator_work(client) -> None:
    owner_id = await _register(
        client, "support-owner@example.com", "correct-horse-player", "Support owner"
    )
    owner_csrf = client.cookies.get("ng_csrf")
    created = await client.post(
        "/api/v1/support/cases",
        headers={"X-CSRF-Token": owner_csrf},
        json={
            "category": "playthrough",
            "subject": "The chapter stopped after a choice",
            "message": "My current story stopped rendering after I selected an action.",
        },
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    assert created.json()["status"] == "open"
    assert "assigned_to" not in created.json()
    own_cases = await client.get("/api/v1/support/cases")
    assert own_cases.status_code == 200, own_cases.text
    assert own_cases.json()["items"][0]["id"] == case_id

    await _register(
        client, "support-other@example.com", "correct-horse-player", "Other player"
    )
    denied = await client.get(f"/api/v1/support/cases/{case_id}")
    assert denied.status_code == 404
    denied_admin = await client.get("/api/v1/admin/support/cases")
    assert denied_admin.status_code == 403

    admin_id, admin_csrf = await _admin_session(
        client, "support-admin@example.com", "correct-horse-admin"
    )
    summary = await client.get("/api/v1/admin/support/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["by_status"]["open"] == 1
    queue = await client.get("/api/v1/admin/support/cases")
    assert queue.status_code == 200, queue.text
    assert queue.json()["items"][0]["player"]["id"] == owner_id
    operators = await client.get("/api/v1/admin/support/operators")
    assert operators.status_code == 200, operators.text
    assert any(item["id"] == admin_id for item in operators.json()["items"])
    inspected = await client.post(
        f"/api/v1/admin/support/cases/{case_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={"reason": "Review the player-provided recovery details before assignment"},
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["messages"][0]["body"] == "My current story stopped rendering after I selected an action."

    assigned = await client.put(
        f"/api/v1/admin/support/cases/{case_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "status": "in_progress",
            "priority": "high",
            "assigned_to": admin_id,
            "reason": "Take ownership of a player-blocking story issue",
        },
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assigned_to"] == admin_id
    reply = await client.post(
        f"/api/v1/admin/support/cases/{case_id}/messages",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "message": "We are reviewing the recovery path. Please avoid starting a duplicate story.",
            "status": "waiting_user",
            "reason": "Ask the player to preserve the affected session",
        },
    )
    assert reply.status_code == 201, reply.text

    signed_in = await client.post(
        "/api/v1/auth/login",
        json={"email": "support-owner@example.com", "password": "correct-horse-player"},
    )
    assert signed_in.status_code == 200, signed_in.text
    detail = await client.get(f"/api/v1/support/cases/{case_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "waiting_user"
    assert [message["author_role"] for message in detail.json()["messages"]] == ["player", "admin"]
    assert all("author_id" not in message for message in detail.json()["messages"])
    private_access = await client.get("/api/v1/settings/privacy/access-log")
    assert private_access.status_code == 200, private_access.text
    assert any(
        entry["reason"] == "Review the player-provided recovery details before assignment"
        for entry in private_access.json()["entries"]
    )
    denied_inspection = await client.post(
        f"/api/v1/admin/support/cases/{case_id}",
        headers={"X-CSRF-Token": client.cookies.get("ng_csrf")},
        json={"reason": "Players cannot use operator support inspection"},
    )
    assert denied_inspection.status_code == 403
    inbox = await client.get("/api/v1/notifications")
    assert inbox.status_code == 200, inbox.text
    assert inbox.json()["unread_total"] == 1
    notification = inbox.json()["items"][0]
    assert notification["kind"] == "support.reply"
    assert notification["href"] == "/support"
    marked = await client.put(
        f"/api/v1/notifications/{notification['id']}/read",
        headers={"X-CSRF-Token": client.cookies.get("ng_csrf")},
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["read_at"] is not None
    assert (await client.get("/api/v1/notifications")).json()["unread_total"] == 0
    player_reply = await client.post(
        f"/api/v1/support/cases/{case_id}/messages",
        headers={"X-CSRF-Token": client.cookies.get("ng_csrf")},
        json={"message": "Understood. I will keep this story available for review."},
    )
    assert player_reply.status_code == 201, player_reply.text

    import sqlalchemy as sa

    import database.session as db_session
    from database.models.platform import AuditLogORM

    maker = db_session.get_sessionmaker()
    async with maker() as session:
        actions = set(
            (
                await session.scalars(
                    sa.select(AuditLogORM.action).where(
                        AuditLogORM.target_id == case_id
                    )
                )
            ).all()
        )
    assert {
        "support.case_created",
        "support.case_inspected",
        "support.case_updated",
        "support.case_replied",
    }.issubset(actions)

"""Commercial-credit boundaries: append-only, idempotent and administrator guarded."""

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


async def _admin_session(
    client, email: str, password: str, *, include_mfa_secret: bool = False
) -> str | tuple[str, str, str]:
    import database.session as db_session
    from apps.api.security import _totp
    from database.models.platform import UserRoleORM
    from engine.core.ids import new_id

    admin_id = await _register(client, email, password, "管理员")
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
    confirmation = await client.post(
        "/api/v1/auth/mfa/confirm",
        headers={"X-CSRF-Token": csrf},
        json={"code": _totp(enrollment.json()["secret"], int(time.time() // 30))},
    )
    assert confirmation.status_code == 200, confirmation.text
    return (
        (csrf, enrollment.json()["secret"], confirmation.json()["recovery_codes"][0])
        if include_mfa_secret
        else csrf
    )


async def test_administrator_adjusts_an_append_only_wallet_with_idempotency(client) -> None:
    player_id = await _register(
        client, "wallet-player@example.com", "correct-horse-player", "余额玩家"
    )
    csrf = await _admin_session(client, "wallet-admin@example.com", "correct-horse-admin")
    payload = {
        "credit_delta": 300,
        "entry_type": "grant",
        "reason": "新玩家体验额度",
        "idempotency_key": "campaign-wallet-player-001",
    }
    granted = await client.post(
        f"/api/v1/admin/commerce/users/{player_id}/adjustments",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["balance"] == 300
    assert granted.json()["idempotent_replay"] is False

    replay = await client.post(
        f"/api/v1/admin/commerce/users/{player_id}/adjustments",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["balance"] == 300
    assert replay.json()["idempotent_replay"] is True

    summary = await client.get("/api/v1/admin/commerce/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["wallet_accounts"] == 1
    assert summary.json()["credits_outstanding"] == 300

    signed_in = await client.post(
        "/api/v1/auth/login",
        json={"email": "wallet-player@example.com", "password": "correct-horse-player"},
    )
    assert signed_in.status_code == 200, signed_in.text
    wallet = await client.get("/api/v1/commerce/wallet")
    assert wallet.status_code == 200, wallet.text
    assert wallet.json()["balance"] == 300
    assert wallet.json()["entries"][0]["reason"] == "新玩家体验额度"


async def test_wallet_debit_cannot_overdraw_or_reuse_a_conflicting_key(client) -> None:
    player_id = await _register(
        client, "wallet-limit@example.com", "correct-horse-player", "余额边界"
    )
    csrf = await _admin_session(client, "wallet-limit-admin@example.com", "correct-horse-admin")
    first = await client.post(
        f"/api/v1/admin/commerce/users/{player_id}/adjustments",
        headers={"X-CSRF-Token": csrf},
        json={
            "credit_delta": 100,
            "reason": "服务补偿",
            "idempotency_key": "wallet-limit-grant-001",
        },
    )
    assert first.status_code == 200, first.text
    overdraw = await client.post(
        f"/api/v1/admin/commerce/users/{player_id}/adjustments",
        headers={"X-CSRF-Token": csrf},
        json={
            "credit_delta": -101,
            "reason": "不应透支",
            "idempotency_key": "wallet-limit-debit-001",
        },
    )
    assert overdraw.status_code == 409
    conflict = await client.post(
        f"/api/v1/admin/commerce/users/{player_id}/adjustments",
        headers={"X-CSRF-Token": csrf},
        json={
            "credit_delta": 101,
            "reason": "冲突的重复请求",
            "idempotency_key": "wallet-limit-grant-001",
        },
    )
    assert conflict.status_code == 409


async def test_a_player_cannot_access_commercial_operations(client) -> None:
    target_id = await _register(
        client, "wallet-target@example.com", "correct-horse-player", "目标玩家"
    )
    await _register(client, "wallet-nonadmin@example.com", "correct-horse-user", "普通玩家")
    csrf = client.cookies.get("ng_csrf")
    denied = await client.post(
        f"/api/v1/admin/commerce/users/{target_id}/adjustments",
        headers={"X-CSRF-Token": csrf},
        json={
            "credit_delta": 100,
            "reason": "越权尝试",
            "idempotency_key": "wallet-nonadmin-001",
        },
    )
    assert denied.status_code == 403


async def test_catalog_is_price_transparent_but_cannot_start_checkout(client) -> None:
    """Only active packages are public; writing them is an audited admin action."""

    initial = await client.get("/api/v1/commerce/catalog")
    assert initial.status_code == 200, initial.text
    assert initial.json() == {"currency": "CNY", "items": [], "checkout_live": False}

    csrf = await _admin_session(client, "catalog-admin@example.com", "correct-horse-admin")
    configured = await client.put(
        "/api/v1/admin/commerce/catalog",
        headers={"X-CSRF-Token": csrf},
        json={
            "currency": "cny",
            "items": [
                {
                    "code": "starter_100",
                    "name": "Starter credits",
                    "description": "A transparent launch package",
                    "credits": 100,
                    "price_minor": 1000,
                    "badge": "Starter",
                    "sort_order": 10,
                    "active": True,
                },
                {
                    "code": "future_pack",
                    "name": "Hidden until launch",
                    "credits": 500,
                    "price_minor": 4500,
                    "active": False,
                },
            ],
            "reason": "Prepare transparent launch pricing without enabling a processor",
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["currency"] == "CNY"
    assert configured.json()["checkout_live"] is False
    assert len(configured.json()["items"]) == 2

    public_catalog = await client.get("/api/v1/commerce/catalog")
    assert public_catalog.status_code == 200, public_catalog.text
    assert public_catalog.json()["checkout_live"] is False
    assert [item["code"] for item in public_catalog.json()["items"]] == ["starter_100"]
    assert public_catalog.json()["items"][0]["price_minor"] == 1000

    audit = await client.get("/api/v1/admin/audit-logs?action_prefix=commerce.catalog")
    assert audit.status_code == 200, audit.text
    assert any(item["action"] == "commerce.catalog_changed" for item in audit.json()["items"])

    await _register(client, "catalog-player@example.com", "correct-horse-player", "Catalog player")
    denied = await client.put(
        "/api/v1/admin/commerce/catalog",
        headers={"X-CSRF-Token": client.cookies.get("ng_csrf")},
        json={
            "currency": "CNY",
            "items": [],
            "reason": "A player must not change price transparency",
        },
    )
    assert denied.status_code == 403


async def test_bounded_campaign_claims_are_idempotent_and_admin_audited(client) -> None:
    """A promotion cannot exceed its cap or grant the same player twice."""

    from datetime import UTC, datetime, timedelta

    await _register(client, "campaign-first@example.com", "correct-horse-player", "First claimant")
    await _register(client, "campaign-second@example.com", "correct-horse-player", "Second claimant")
    csrf = await _admin_session(client, "campaign-admin@example.com", "correct-horse-admin")
    now = datetime.now(UTC)
    created = await client.post(
        "/api/v1/admin/commerce/campaigns",
        headers={"X-CSRF-Token": csrf},
        json={
            "code": "launch_120",
            "name": "Launch welcome credits",
            "description": "One-time welcome grant for the launch cohort.",
            "credit_amount": 120,
            "status": "active",
            "starts_at": (now - timedelta(minutes=1)).isoformat(),
            "ends_at": (now + timedelta(days=1)).isoformat(),
            "max_redemptions": 1,
            "reason": "Launch cohort welcome-credit campaign",
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["claimable"] is True
    admin_campaigns = await client.get("/api/v1/admin/commerce/campaigns")
    assert admin_campaigns.status_code == 200, admin_campaigns.text
    assert admin_campaigns.json()["items"][0]["code"] == "launch_120"

    signed_in = await client.post(
        "/api/v1/auth/login",
        json={"email": "campaign-first@example.com", "password": "correct-horse-player"},
    )
    assert signed_in.status_code == 200, signed_in.text
    player_csrf = client.cookies.get("ng_csrf")
    offered = await client.get("/api/v1/commerce/campaigns")
    assert offered.status_code == 200, offered.text
    assert [item["code"] for item in offered.json()["items"]] == ["launch_120"]
    claimed = await client.post(
        "/api/v1/commerce/campaigns/launch_120/redeem",
        headers={"X-CSRF-Token": player_csrf},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["idempotent_replay"] is False
    assert claimed.json()["balance"] == 120
    replay = await client.post(
        "/api/v1/commerce/campaigns/launch_120/redeem",
        headers={"X-CSRF-Token": player_csrf},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["balance"] == 120

    second = await client.post(
        "/api/v1/auth/login",
        json={"email": "campaign-second@example.com", "password": "correct-horse-player"},
    )
    assert second.status_code == 200, second.text
    cap_reached = await client.post(
        "/api/v1/commerce/campaigns/launch_120/redeem",
        headers={"X-CSRF-Token": client.cookies.get("ng_csrf")},
    )
    assert cap_reached.status_code == 409

    import sqlalchemy as sa

    import database.session as db_session
    from database.models.platform import AuditLogORM

    maker = db_session.get_sessionmaker()
    async with maker() as session:
        actions = set(
            (
                await session.scalars(
                    sa.select(AuditLogORM.action).where(
                        AuditLogORM.action.like("commerce.campaign%")
                    )
                )
            ).all()
        )
    assert {"commerce.campaign_created", "commerce.campaign_redeemed"}.issubset(actions)


async def test_ended_campaign_cannot_be_silently_reactivated(client) -> None:
    """Ending a grant is terminal; a new approved campaign is required to restart it."""

    from datetime import UTC, datetime, timedelta

    csrf = await _admin_session(client, "campaign-end-admin@example.com", "correct-horse-admin")
    now = datetime.now(UTC)
    created = await client.post(
        "/api/v1/admin/commerce/campaigns",
        headers={"X-CSRF-Token": csrf},
        json={
            "code": "end_once",
            "name": "End once",
            "credit_amount": 10,
            "status": "active",
            "starts_at": (now - timedelta(minutes=1)).isoformat(),
            "ends_at": (now + timedelta(days=1)).isoformat(),
            "reason": "Prepare a terminal status-control test",
        },
    )
    assert created.status_code == 200, created.text
    ended = await client.put(
        f"/api/v1/admin/commerce/campaigns/{created.json()['id']}/status",
        headers={"X-CSRF-Token": csrf},
        json={"status": "ended", "reason": "Close the promotion permanently"},
    )
    assert ended.status_code == 200, ended.text
    reactivation = await client.put(
        f"/api/v1/admin/commerce/campaigns/{created.json()['id']}/status",
        headers={"X-CSRF-Token": csrf},
        json={"status": "active", "reason": "This must require a new campaign"},
    )
    assert reactivation.status_code == 409


async def test_turn_billing_policy_reserves_and_settles_once(client) -> None:
    """The wallet is charged only once, after a durable turn reservation."""

    import sqlalchemy as sa

    import database.session as db_session
    from apps.api.billing import reserve_turn_credits, settle_turn_credits, wallet_balance
    from database.models.platform import WalletHoldORM, WalletLedgerORM
    from database.repositories.sql import SqlUnitOfWork

    player_id = await _register(
        client, "wallet-billing@example.com", "correct-horse-player", "Billing player"
    )
    csrf = await _admin_session(client, "wallet-billing-admin@example.com", "correct-horse-admin")
    configured = await client.put(
        "/api/v1/admin/commerce/billing-policy",
        headers={"X-CSRF-Token": csrf},
        json={
            "mode": "wallet",
            "credit_label": "Story credit",
            "cost_microunits_per_credit": 10_000,
            "turn_reserve_credits": 100,
            "hold_minutes": 20,
            "reason": "Enable verified turn billing for the test deployment",
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["enabled"] is True

    granted = await client.post(
        f"/api/v1/admin/commerce/users/{player_id}/adjustments",
        headers={"X-CSRF-Token": csrf},
        json={
            "credit_delta": 300,
            "reason": "Billing test grant",
            "idempotency_key": "wallet-billing-grant-001",
            "entry_type": "grant",
        },
    )
    assert granted.status_code == 200, granted.text

    maker = db_session.get_sessionmaker()
    async with maker() as session:
        uow = SqlUnitOfWork(session)
        reservation = await reserve_turn_credits(
            uow,
            user_id=player_id,
            playthrough_id=None,
            idempotency_key="wallet-billing-turn-001",
        )
        assert reservation is not None
        assert reservation.reserved_credits == 100
        charged = await settle_turn_credits(
            uow,
            reservation,
            billable_cost_microunits=15_001,
            action_completed=True,
        )
        assert charged == 2
        assert (
            await settle_turn_credits(
                uow,
                reservation,
                billable_cost_microunits=15_001,
                action_completed=True,
            )
            == 2
        )
        assert await wallet_balance(uow, player_id) == 298
        entries = (
            await session.scalars(
                sa.select(WalletLedgerORM).where(WalletLedgerORM.user_id == player_id)
            )
        ).all()
        assert [entry.credit_delta for entry in entries].count(-2) == 1
        hold = await session.scalar(
            sa.select(WalletHoldORM).where(WalletHoldORM.id == reservation.hold_id)
        )
        assert hold is not None and hold.status == "settled"
        # A completed action can be safely retried with the same request key.
        replay = await reserve_turn_credits(
            uow,
            user_id=player_id,
            playthrough_id=None,
            idempotency_key="wallet-billing-turn-001",
        )
        assert replay == reservation
        opening = await reserve_turn_credits(
            uow,
            user_id=player_id,
            playthrough_id=None,
            idempotency_key="wallet-billing-opening-001",
            reservation_kind="opening",
        )
        assert opening is not None
        assert (
            await settle_turn_credits(
                uow,
                opening,
                billable_cost_microunits=10_000,
                action_completed=True,
            )
            == 1
        )
        opening_entry = await session.scalar(
            sa.select(WalletLedgerORM).where(
                WalletLedgerORM.user_id == player_id,
                WalletLedgerORM.source_id == opening.hold_id,
            )
        )
        assert opening_entry is not None
        assert opening_entry.source_type == "playthrough_opening"
        assert opening_entry.entry_metadata["reservation_kind"] == "opening"


async def test_billing_policy_requires_credits_before_a_model_request(client) -> None:
    """A paid opening is protected before a new world or a later turn exists."""

    player_id = await _register(
        client, "wallet-empty@example.com", "correct-horse-player", "Empty wallet"
    )
    admin_session = await _admin_session(
        client,
        "wallet-empty-admin@example.com",
        "correct-horse-admin",
        include_mfa_secret=True,
    )
    assert isinstance(admin_session, tuple)
    csrf, _admin_mfa_secret, admin_recovery_code = admin_session
    configured = await client.put(
        "/api/v1/admin/commerce/billing-policy",
        headers={"X-CSRF-Token": csrf},
        json={
            "mode": "wallet",
            "credit_label": "Story credit",
            "cost_microunits_per_credit": 10_000,
            "turn_reserve_credits": 100,
            "hold_minutes": 20,
            "reason": "Verify low-balance protection",
        },
    )
    assert configured.status_code == 200, configured.text

    signed_in = await client.post(
        "/api/v1/auth/login",
        json={"email": "wallet-empty@example.com", "password": "correct-horse-player"},
    )
    assert signed_in.status_code == 200, signed_in.text
    player_csrf = client.cookies.get("ng_csrf")
    catalog = (await client.get("/api/v1/catalog/releases")).json()["items"]
    release = next(item for item in catalog if "春日坂" in item["title"])
    started = await client.post(
        "/api/v1/playthroughs",
        headers={"X-CSRF-Token": player_csrf},
        json={
            "release_id": release["id"],
            "name": "Billing test",
            "age": 20,
            "gender": "female",
            "idempotency_key": "wallet-empty-opening-001",
        },
    )
    assert started.status_code == 402, started.text
    assert started.json()["detail"]["code"] == "insufficient_credits"
    assert (await client.get("/api/v1/playthroughs")).json() == []

    admin_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "wallet-empty-admin@example.com", "password": "correct-horse-admin"},
    )
    assert admin_login.status_code == 200, admin_login.text
    stepped_up = await client.post(
        "/api/v1/auth/mfa/step-up",
        headers={"X-CSRF-Token": client.cookies.get("ng_csrf")},
        json={"code": admin_recovery_code},
    )
    assert stepped_up.status_code == 200, stepped_up.text
    granted = await client.post(
        f"/api/v1/admin/commerce/users/{player_id}/adjustments",
        headers={"X-CSRF-Token": client.cookies.get("ng_csrf")},
        json={
            "credit_delta": 100,
            "entry_type": "grant",
            "reason": "Permit one paid opening",
            "idempotency_key": "wallet-empty-opening-grant-001",
        },
    )
    assert granted.status_code == 200, granted.text
    player_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "wallet-empty@example.com", "password": "correct-horse-player"},
    )
    assert player_login.status_code == 200, player_login.text
    player_csrf = client.cookies.get("ng_csrf")
    started = await client.post(
        "/api/v1/playthroughs",
        headers={"X-CSRF-Token": player_csrf},
        json={
            "release_id": release["id"],
            "name": "Billing test",
            "age": 20,
            "gender": "female",
            "idempotency_key": "wallet-empty-opening-001",
        },
    )
    assert started.status_code == 201, started.text
    replay = await client.post(
        "/api/v1/playthroughs",
        headers={"X-CSRF-Token": player_csrf},
        json={
            "release_id": release["id"],
            "name": "Billing test",
            "age": 20,
            "gender": "female",
            "idempotency_key": "wallet-empty-opening-001",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["id"] == started.json()["id"]
    assert player_id


async def test_super_administrator_role_is_bootstrapped_and_dual_controlled(client) -> None:
    """A highest-role change needs a separate requester and approver."""

    from datetime import UTC, datetime

    import sqlalchemy as sa

    import database.session as db_session
    from apps.api.deps import settings_dep
    from database.bootstrap import ensure_configured_super_admins
    from database.models.platform import UserORM, UserRoleORM
    from engine.core.ids import new_id

    target_id = await _register(
        client, "super-target@example.com", "correct-horse-player", "Protected account"
    )
    settings = settings_dep()
    settings.super_admin_emails = "super-target@example.com"
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        target = await session.get(UserORM, target_id)
        assert target is not None
        target.email_verified_at = datetime.now(UTC)
        await session.commit()
    assert await ensure_configured_super_admins(settings) == 1
    async with maker() as session:
        target_roles = set(
            (
                await session.scalars(
                    sa.select(UserRoleORM.role).where(UserRoleORM.user_id == target_id)
                )
            ).all()
        )
    assert {"admin", "super_admin"}.issubset(target_roles)

    normal_admin_id = await _register(
        client, "normal-admin@example.com", "correct-horse-admin", "Normal admin"
    )
    async with maker() as session:
        session.add(UserRoleORM(id=new_id(), user_id=normal_admin_id, role="admin"))
        await session.commit()
    csrf = client.cookies.get("ng_csrf")
    from apps.api.security import _totp

    enrollment = await client.post(
        "/api/v1/auth/mfa/enroll",
        headers={"X-CSRF-Token": csrf},
        json={"password": "correct-horse-admin"},
    )
    assert enrollment.status_code == 200, enrollment.text
    confirmation = await client.post(
        "/api/v1/auth/mfa/confirm",
        headers={"X-CSRF-Token": csrf},
        json={"code": _totp(enrollment.json()["secret"], int(time.time() // 30))},
    )
    assert confirmation.status_code == 200, confirmation.text

    ordinary_attempt = await client.put(
        f"/api/v1/admin/users/{target_id}/roles",
        headers={"X-CSRF-Token": csrf},
        json={"roles": ["player"], "reason": "An ordinary admin should not demote this account"},
    )
    assert ordinary_attempt.status_code == 403

    # Bootstrap a second super admin out-of-band, as a deployment operator
    # would.  The existing MFA-authenticated session immediately gains access.
    async with maker() as session:
        session.add(UserRoleORM(id=new_id(), user_id=normal_admin_id, role="super_admin"))
        await session.commit()
    governance = await client.get("/api/v1/admin/governance/super-admins")
    assert governance.status_code == 200, governance.text
    assert {item["id"] for item in governance.json()["items"]} == {target_id, normal_admin_id}

    requested = await client.put(
        f"/api/v1/admin/users/{target_id}/super-admin",
        headers={"X-CSRF-Token": csrf},
        json={"enabled": False, "reason": "Rotate the break-glass administrator"},
    )
    assert requested.status_code == 200, requested.text
    assert requested.json()["status"] == "pending"
    approval_id = requested.json()["id"]
    self_approval = await client.post(
        f"/api/v1/admin/governance/super-admin-approvals/{approval_id}/approve",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "A requester must not approve their own elevation request"},
    )
    assert self_approval.status_code == 409
    async with maker() as session:
        target_roles = set(
            (
                await session.scalars(
                    sa.select(UserRoleORM.role).where(UserRoleORM.user_id == target_id)
                )
            ).all()
        )
    assert "super_admin" in target_roles

    target_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "super-target@example.com", "password": "correct-horse-player"},
    )
    assert target_login.status_code == 200, target_login.text
    target_csrf = client.cookies.get("ng_csrf")
    target_enrollment = await client.post(
        "/api/v1/auth/mfa/enroll",
        headers={"X-CSRF-Token": target_csrf},
        json={"password": "correct-horse-player"},
    )
    assert target_enrollment.status_code == 200, target_enrollment.text
    target_confirmation = await client.post(
        "/api/v1/auth/mfa/confirm",
        headers={"X-CSRF-Token": target_csrf},
        json={"code": _totp(target_enrollment.json()["secret"], int(time.time() // 30))},
    )
    assert target_confirmation.status_code == 200, target_confirmation.text
    approved = await client.post(
        f"/api/v1/admin/governance/super-admin-approvals/{approval_id}/approve",
        headers={"X-CSRF-Token": target_csrf},
        json={"reason": "Confirm the on-call super administrator rotation"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    async with maker() as session:
        remaining_super_admins = set(
            (
                await session.scalars(
                    sa.select(UserRoleORM.user_id).where(UserRoleORM.role == "super_admin")
                )
            ).all()
        )
    assert remaining_super_admins == {normal_admin_id}


async def test_admin_audit_explorer_is_filterable_and_reviewer_safe(client) -> None:
    """Operations can investigate changes without widening reviewer visibility."""

    import database.session as db_session
    from database.models.platform import UserRoleORM
    from engine.core.ids import new_id

    target_id = await _register(
        client, "audit-target@example.com", "correct-horse-player", "Audit target"
    )
    csrf = await _admin_session(client, "audit-admin@example.com", "correct-horse-admin")
    adjusted = await client.post(
        f"/api/v1/admin/commerce/users/{target_id}/adjustments",
        headers={"X-CSRF-Token": csrf},
        json={
            "credit_delta": 50,
            "entry_type": "grant",
            "reason": "Create an auditable operator event",
            "idempotency_key": "audit-explorer-grant-001",
        },
    )
    assert adjusted.status_code == 200, adjusted.text
    audit = await client.get("/api/v1/admin/audit-logs?action_prefix=wallet.")
    assert audit.status_code == 200, audit.text
    assert any(item["action"] == "wallet.adjustment" for item in audit.json()["items"])
    assert audit.json()["next_before"] is None
    summary = await client.get("/api/v1/admin/audit-summary?hours=24")
    assert summary.status_code == 200, summary.text
    assert any(item["action"] == "wallet.adjustment" for item in summary.json()["actions"])
    operations = await client.get("/api/v1/admin/system")
    assert operations.status_code == 200, operations.text
    assert operations.json()["operations_window_hours"] == 24
    assert operations.json()["active_sessions"] >= 1
    assert operations.json()["support_open_cases"] >= 0
    assert operations.json()["support_unassigned_cases"] >= 0
    assert isinstance(operations.json()["model_usage_24h"], list)

    reviewer_id = await _register(
        client, "audit-reviewer@example.com", "correct-horse-reviewer", "Reviewer"
    )
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        session.add(UserRoleORM(id=new_id(), user_id=reviewer_id, role="reviewer"))
        await session.commit()
    reviewer_log = await client.get("/api/v1/creator/audit-logs?limit=100")
    assert reviewer_log.status_code == 200, reviewer_log.text
    assert all(not item["action"].startswith("wallet.") for item in reviewer_log.json())


async def test_admin_operations_alerts_are_actionable_and_do_not_expose_player_data(client) -> None:
    """Operations sees durable risk counts, while a player cannot query them."""

    from datetime import UTC, datetime, timedelta

    import database.session as db_session
    from database.models.platform import AuditLogORM, SupportCaseORM, UsageLedgerORM, WalletHoldORM
    from engine.core.ids import new_id

    player_id = await _register(
        client, "operations-alert-player@example.com", "correct-horse-player", "Risk signal player"
    )
    await _admin_session(client, "operations-alert-admin@example.com", "correct-horse-admin")
    now = datetime.now(UTC)
    maker = db_session.get_sessionmaker()
    async with maker() as session:
        session.add_all(
            [
                *[
                    UsageLedgerORM(
                        id=new_id(),
                        user_id=player_id,
                        provider="platform-test",
                        model="ops-test",
                        success=False,
                        created_at=now,
                    )
                    for _ in range(4)
                ],
                UsageLedgerORM(
                    id=new_id(),
                    user_id=player_id,
                    provider="platform-test",
                    model="ops-test",
                    success=True,
                    created_at=now,
                ),
                WalletHoldORM(
                    id=new_id(),
                    user_id=player_id,
                    idempotency_key="operations-alert-expired-hold",
                    status="held",
                    reserved_credits=10,
                    settled_credits=0,
                    cost_microunits_per_credit=10_000,
                    expires_at=now - timedelta(minutes=5),
                    hold_metadata={},
                ),
                SupportCaseORM(
                    id=new_id(),
                    user_id=player_id,
                    category="technical",
                    status="open",
                    priority="urgent",
                    subject="Urgent routing test",
                ),
                *[
                    AuditLogORM(
                        id=new_id(),
                        actor_id=None,
                        action="auth.login_anomaly",
                        target_type="user",
                        target_id=player_id,
                        details={},
                        created_at=now,
                    )
                    for _ in range(3)
                ],
            ]
        )
        await session.commit()

    signals = await client.get("/api/v1/admin/operations-alerts")
    assert signals.status_code == 200, signals.text
    payload = signals.json()
    codes = {item["code"] for item in payload["alerts"]}
    assert {
        "llm_failure_rate_critical",
        "expired_wallet_holds",
        "urgent_support_unassigned",
        "login_anomaly_cluster",
    }.issubset(codes)
    assert payload["counts"]["critical"] >= 2
    assert all("email" not in str(item).lower() for item in payload["alerts"])
    assert next(item for item in payload["alerts"] if item["code"] == "urgent_support_unassigned")[
        "href"
    ] == "#support-operations"

    await _register(
        client, "operations-alert-nonadmin@example.com", "correct-horse-player", "No operations access"
    )
    assert (await client.get("/api/v1/admin/operations-alerts")).status_code == 403

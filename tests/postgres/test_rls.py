from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.tenancy import set_tenant_context
from database.models.orm import WorldORM
from database.models.platform import (
    ContentReleaseORM,
    CreditCampaignORM,
    PlaythroughORM,
    SuperAdminApprovalORM,
    SupportCaseMessageORM,
    SupportCaseORM,
    UserNotificationORM,
    UserORM,
    UserRoleORM,
    WalletHoldORM,
    WalletLedgerORM,
)
from database.repositories.sql import SqlUnitOfWork
from database.seeding import persist_bundle
from engine.contentpack.pack import load_content_pack
from engine.core.ids import PLAYER_KEY
from engine.world.seeder import PlayerSpec, build_world
from engine.world.state_view import build_world_state

pytestmark = pytest.mark.postgres_integration

OWNER_URL = os.getenv("TEST_POSTGRES_OWNER_URL", "")
APP_URL = os.getenv("TEST_POSTGRES_APP_URL", "")


@pytest.mark.skipif(
    not OWNER_URL or not APP_URL,
    reason="set TEST_POSTGRES_OWNER_URL and TEST_POSTGRES_APP_URL",
)
async def test_application_role_cannot_cross_playthrough_tenants() -> None:
    owner_engine = create_async_engine(OWNER_URL)
    app_engine = create_async_engine(APP_URL)
    owner_maker = async_sessionmaker(owner_engine, expire_on_commit=False)
    app_maker = async_sessionmaker(app_engine, expire_on_commit=False)
    (
        user_a,
        user_b,
        play_a,
        play_b,
        world_a,
        world_b,
        campaign_active,
        campaign_draft,
        support_case_a,
        support_case_b,
        notification_a,
        notification_b,
    ) = (
        str(uuid.uuid4()) for _ in range(12)
    )

    try:
        async with owner_maker() as session:
            release_id = await session.scalar(
                sa.select(ContentReleaseORM.id)
                .where(ContentReleaseORM.withdrawn_at.is_(None))
                .limit(1)
            )
            assert release_id is not None, "bootstrap an official release before RLS tests"
            session.add_all(
                [
                    UserORM(
                        id=user_a,
                        email=f"{user_a}@example.invalid",
                        password_hash="!test!",
                        display_name="RLS A",
                    ),
                    UserORM(
                        id=user_b,
                        email=f"{user_b}@example.invalid",
                        password_hash="!test!",
                        display_name="RLS B",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    WalletLedgerORM(
                        id=str(uuid.uuid4()),
                        user_id=user_a,
                        credit_delta=500,
                        entry_type="grant",
                        source_type="test",
                        idempotency_key="rls-grant-a",
                        reason="RLS test grant",
                    ),
                    WalletLedgerORM(
                        id=str(uuid.uuid4()),
                        user_id=user_b,
                        credit_delta=500,
                        entry_type="grant",
                        source_type="test",
                        idempotency_key="rls-grant-b",
                        reason="RLS test grant",
                    ),
                ]
            )
            session.add_all(
                [
                    PlaythroughORM(
                        id=play_a,
                        user_id=user_a,
                        release_id=release_id,
                        scenario_key="entry",
                        world_id=world_a,
                    ),
                    PlaythroughORM(
                        id=play_b,
                        user_id=user_b,
                        release_id=release_id,
                        scenario_key="entry",
                        world_id=world_b,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    WorldORM(
                        id=world_a,
                        name="Tenant A world",
                        playthrough_id=play_a,
                        release_id=release_id,
                    ),
                    WorldORM(
                        id=world_b,
                        name="Tenant B world",
                        playthrough_id=play_b,
                        release_id=release_id,
                    ),
                ]
            )
            now = datetime.now(UTC)
            session.add_all(
                [
                    CreditCampaignORM(
                        id=campaign_active,
                        code=f"rls-active-{campaign_active[:8]}",
                        name="Active RLS campaign",
                        credit_amount=100,
                        status="active",
                        starts_at=now - timedelta(minutes=1),
                        ends_at=now + timedelta(days=1),
                        redemption_count=0,
                    ),
                    CreditCampaignORM(
                        id=campaign_draft,
                        code=f"rls-draft-{campaign_draft[:8]}",
                        name="Draft RLS campaign",
                        credit_amount=100,
                        status="draft",
                        starts_at=now - timedelta(minutes=1),
                        ends_at=now + timedelta(days=1),
                        redemption_count=0,
                    ),
                ]
            )
            session.add_all(
                [
                    SupportCaseORM(
                        id=support_case_a,
                        user_id=user_a,
                        category="technical",
                        status="open",
                        priority="normal",
                        subject="Tenant A support case",
                    ),
                    SupportCaseORM(
                        id=support_case_b,
                        user_id=user_b,
                        category="technical",
                        status="open",
                        priority="normal",
                        subject="Tenant B support case",
                    ),
                ]
            )
            session.add_all(
                [
                    SupportCaseMessageORM(
                        id=str(uuid.uuid4()),
                        case_id=support_case_a,
                        author_id=user_a,
                        author_role="player",
                        body="Tenant A initial message",
                    ),
                    SupportCaseMessageORM(
                        id=str(uuid.uuid4()),
                        case_id=support_case_b,
                        author_id=user_b,
                        author_role="player",
                        body="Tenant B initial message",
                    ),
                ]
            )
            session.add_all(
                [
                    UserNotificationORM(
                        id=notification_a,
                        user_id=user_a,
                        kind="support.reply",
                        title="Tenant A notification",
                        body="Private inbox row",
                        href="/support",
                    ),
                    UserNotificationORM(
                        id=notification_b,
                        user_id=user_b,
                        kind="support.reply",
                        title="Tenant B notification",
                        body="Private inbox row",
                        href="/support",
                    ),
                ]
            )
            await session.commit()

        async with app_maker() as session:
            role = (
                await session.execute(
                    sa.text(
                        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
                    )
                )
            ).one()
            assert role == (False, False)

            await session.execute(
                sa.text("SELECT set_config('app.current_user_id', :user_id, true)"),
                {"user_id": user_a},
            )
            visible_plays = set((await session.scalars(sa.select(PlaythroughORM.id))).all())
            visible_worlds = set((await session.scalars(sa.select(WorldORM.id))).all())
            assert play_a in visible_plays
            assert play_b not in visible_plays
            assert world_a in visible_worlds
            assert world_b not in visible_worlds
            assert await session.get(PlaythroughORM, play_b) is None
            visible_campaigns = set((await session.scalars(sa.select(CreditCampaignORM.id))).all())
            assert campaign_active in visible_campaigns
            assert campaign_draft not in visible_campaigns
            visible_support_cases = set((await session.scalars(sa.select(SupportCaseORM.id))).all())
            assert support_case_a in visible_support_cases
            assert support_case_b not in visible_support_cases
            visible_support_messages = set(
                (await session.scalars(sa.select(SupportCaseMessageORM.case_id))).all()
            )
            assert visible_support_messages == {support_case_a}
            visible_notifications = set(
                (await session.scalars(sa.select(UserNotificationORM.id))).all()
            )
            assert visible_notifications == {notification_a}
            own_notification_update = await session.execute(
                sa.update(UserNotificationORM)
                .where(UserNotificationORM.id == notification_a)
                .values(read_at=datetime.now(UTC))
            )
            assert getattr(own_notification_update, "rowcount", None) == 1
            other_notification_update = await session.execute(
                sa.update(UserNotificationORM)
                .where(UserNotificationORM.id == notification_b)
                .values(read_at=datetime.now(UTC))
            )
            assert getattr(other_notification_update, "rowcount", None) == 0
            session.add(
                SupportCaseMessageORM(
                    id=str(uuid.uuid4()),
                    case_id=support_case_a,
                    author_id=user_a,
                    author_role="player",
                    body="Tenant A follow-up",
                )
            )
            await session.flush()
            inactive_campaign_update = await session.execute(
                sa.update(CreditCampaignORM)
                .where(CreditCampaignORM.id == campaign_draft)
                .values(redemption_count=1)
            )
            assert getattr(inactive_campaign_update, "rowcount", None) == 0
            visible_wallet_users = set(
                (await session.scalars(sa.select(WalletLedgerORM.user_id))).all()
            )
            assert visible_wallet_users == {user_a}

            # The player-scoped application transaction must be able to
            # reserve and settle its own platform-model turn, but it cannot
            # see or use the other player's credits.
            hold = WalletHoldORM(
                id=str(uuid.uuid4()),
                user_id=user_a,
                idempotency_key="rls-hold-a",
                status="held",
                reserved_credits=100,
                settled_credits=0,
                cost_microunits_per_credit=10_000,
                expires_at=datetime.now(UTC) + timedelta(minutes=20),
                hold_metadata={},
            )
            session.add(hold)
            await session.flush()
            session.add(
                WalletLedgerORM(
                    id=str(uuid.uuid4()),
                    user_id=user_a,
                    credit_delta=-25,
                    entry_type="usage",
                    source_type="playthrough_turn",
                    source_id=hold.id,
                    idempotency_key="rls-settlement-a",
                    reason="RLS test settlement",
                )
            )
            await session.flush()
            assert await session.get(WalletHoldORM, hold.id) is not None

            result = await session.execute(
                sa.update(PlaythroughORM)
                .where(PlaythroughORM.id == play_b)
                .values(status="deleted")
            )
            assert getattr(result, "rowcount", None) == 0
            await session.rollback()

        async with app_maker() as session:
            await session.execute(
                sa.text("SELECT set_config('app.current_user_id', :user_id, true)"),
                {"user_id": user_a},
            )
            session.add(
                PlaythroughORM(
                    id=str(uuid.uuid4()),
                    user_id=user_b,
                    release_id=release_id,
                    scenario_key="entry",
                )
            )
            with pytest.raises(DBAPIError):
                await session.flush()
            await session.rollback()

        async with app_maker() as session:
            assert list(await session.scalars(sa.select(PlaythroughORM.id))) == []

        # Game orchestration uses multiple durable transactions in one request.
        # The UoW must restore SET LOCAL after each boundary without weakening
        # connection-pool isolation.
        async with app_maker() as session:
            uow = SqlUnitOfWork(session)
            await set_tenant_context(session, user_a)
            assert await session.get(WorldORM, world_a) is not None
            await uow.commit()
            assert await session.get(WorldORM, world_a) is not None
            assert await session.get(WorldORM, world_b) is None
            await uow.rollback()
    finally:
        async with owner_maker() as session:
            await session.execute(
                sa.delete(SupportCaseORM).where(
                    SupportCaseORM.id.in_([support_case_a, support_case_b])
                )
            )
            await session.execute(
                sa.delete(CreditCampaignORM).where(
                    CreditCampaignORM.id.in_([campaign_active, campaign_draft])
                )
            )
            await session.execute(
                sa.delete(WalletHoldORM).where(WalletHoldORM.user_id.in_([user_a, user_b]))
            )
            await session.execute(
                sa.delete(WalletLedgerORM).where(WalletLedgerORM.user_id.in_([user_a, user_b]))
            )
            await session.execute(sa.delete(WorldORM).where(WorldORM.id.in_([world_a, world_b])))
            await session.execute(sa.delete(UserORM).where(UserORM.id.in_([user_a, user_b])))
            await session.commit()
        await app_engine.dispose()
        await owner_engine.dispose()


@pytest.mark.skipif(
    not OWNER_URL or not APP_URL,
    reason="set TEST_POSTGRES_OWNER_URL and TEST_POSTGRES_APP_URL",
)
async def test_super_admin_approval_rls_excludes_non_super_administrators() -> None:
    """The dual-control queue is visible and writable only to super administrators."""

    owner_engine = create_async_engine(OWNER_URL)
    app_engine = create_async_engine(APP_URL)
    owner_maker = async_sessionmaker(owner_engine, expire_on_commit=False)
    app_maker = async_sessionmaker(app_engine, expire_on_commit=False)
    super_admin_a, super_admin_b, player_id, approval_id = (
        str(uuid.uuid4()) for _ in range(4)
    )

    try:
        async with owner_maker() as session:
            session.add_all(
                [
                    UserORM(
                        id=super_admin_a,
                        email=f"{super_admin_a}@example.invalid",
                        password_hash="!test!",
                        display_name="Approval super administrator A",
                    ),
                    UserORM(
                        id=super_admin_b,
                        email=f"{super_admin_b}@example.invalid",
                        password_hash="!test!",
                        display_name="Approval super administrator B",
                    ),
                    UserORM(
                        id=player_id,
                        email=f"{player_id}@example.invalid",
                        password_hash="!test!",
                        display_name="Approval target player",
                    ),
                    UserRoleORM(id=str(uuid.uuid4()), user_id=super_admin_a, role="super_admin"),
                    UserRoleORM(id=str(uuid.uuid4()), user_id=super_admin_b, role="super_admin"),
                    SuperAdminApprovalORM(
                        id=approval_id,
                        requester_id=super_admin_a,
                        target_user_id=player_id,
                        requested_enabled=True,
                        request_reason="RLS approval visibility test",
                        status="pending",
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    ),
                ]
            )
            await session.commit()

        async with app_maker() as session:
            await session.execute(
                sa.text("SELECT set_config('app.current_user_id', :user_id, true)"),
                {"user_id": super_admin_b},
            )
            assert set((await session.scalars(sa.select(SuperAdminApprovalORM.id))).all()) == {
                approval_id
            }

        async with app_maker() as session:
            await session.execute(
                sa.text("SELECT set_config('app.current_user_id', :user_id, true)"),
                {"user_id": player_id},
            )
            assert list(await session.scalars(sa.select(SuperAdminApprovalORM.id))) == []
            session.add(
                SuperAdminApprovalORM(
                    id=str(uuid.uuid4()),
                    requester_id=player_id,
                    target_user_id=super_admin_a,
                    requested_enabled=False,
                    request_reason="This insert must be rejected by RLS",
                    status="pending",
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            with pytest.raises(DBAPIError):
                await session.flush()
            await session.rollback()
    finally:
        async with owner_maker() as session:
            await session.execute(
                sa.delete(SuperAdminApprovalORM).where(
                    SuperAdminApprovalORM.id == approval_id
                )
            )
            await session.execute(
                sa.delete(UserRoleORM).where(
                    UserRoleORM.user_id.in_([super_admin_a, super_admin_b])
                )
            )
            await session.execute(
                sa.delete(UserORM).where(
                    UserORM.id.in_([super_admin_a, super_admin_b, player_id])
                )
            )
            await session.commit()
        await app_engine.dispose()
        await owner_engine.dispose()


@pytest.mark.skipif(
    not OWNER_URL or not APP_URL,
    reason="set TEST_POSTGRES_OWNER_URL and TEST_POSTGRES_APP_URL",
)
async def test_postgres_world_state_snapshot_is_one_owned_statement() -> None:
    owner_engine = create_async_engine(OWNER_URL)
    app_engine = create_async_engine(APP_URL)
    owner_maker = async_sessionmaker(owner_engine, expire_on_commit=False)
    app_maker = async_sessionmaker(app_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex
    user_id = str(uuid.uuid4())
    playthrough_id = str(uuid.uuid4())
    pack = load_content_pack(Path(__file__).resolve().parents[2] / "content", "campus_romance_v1")
    bundle = build_world(
        pack,
        world_seed=f"postgres-snapshot-{suffix}",
        player=PlayerSpec(name="PostgreSQL 玩家", gender="female", age=20),
    )
    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None and bundle.session is not None

    try:
        async with owner_maker() as session:
            release_id = await session.scalar(
                sa.select(ContentReleaseORM.id)
                .where(ContentReleaseORM.withdrawn_at.is_(None))
                .limit(1)
            )
            assert release_id is not None
            session.add(
                UserORM(
                    id=user_id,
                    email=f"snapshot-{suffix}@example.invalid",
                    password_hash="!test!",
                    display_name="Snapshot owner",
                )
            )
            await session.flush()
            session.add(
                PlaythroughORM(
                    id=playthrough_id,
                    user_id=user_id,
                    release_id=release_id,
                    scenario_key="entry",
                    world_id=bundle.world.id,
                    game_session_id=bundle.session.id,
                )
            )
            await session.flush()
            bundle.world.playthrough_id = playthrough_id
            bundle.world.release_id = release_id
            bundle.session.playthrough_id = playthrough_id
            await persist_bundle(session, bundle)
            await session.commit()

        async with app_maker() as session:
            await session.execute(
                sa.text("SELECT set_config('app.current_user_id', :user_id, true)"),
                {"user_id": user_id},
            )
            statements = 0

            def count_statement(*_args: object) -> None:
                nonlocal statements
                statements += 1

            sa.event.listen(app_engine.sync_engine, "before_cursor_execute", count_statement)
            try:
                state = await build_world_state(
                    SqlUnitOfWork(session), pack, bundle.world.id, player.id
                )
            finally:
                sa.event.remove(app_engine.sync_engine, "before_cursor_execute", count_statement)

            assert state.world.id == bundle.world.id
            assert state.player.id == player.id
            assert statements == 1
    finally:
        async with owner_maker() as session:
            await session.execute(sa.delete(WorldORM).where(WorldORM.id == bundle.world.id))
            await session.execute(sa.delete(UserORM).where(UserORM.id == user_id))
            await session.commit()
        await app_engine.dispose()
        await owner_engine.dispose()


@pytest.mark.skipif(
    not OWNER_URL,
    reason="set TEST_POSTGRES_OWNER_URL",
)
async def test_operator_lookup_does_not_deduplicate_over_json_columns() -> None:
    """SELECT DISTINCT over a user row reaches its json columns.

    PostgreSQL has no equality operator for ``json``, so such a query raises
    UndefinedFunctionError. SQLite accepts it happily, which is how the support
    console shipped a query that returned 500 for every administrator.
    """
    from apps.api.routers.support import support_operators

    engine = create_async_engine(OWNER_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    admin_id = str(uuid.uuid4())
    try:
        async with maker() as session:
            session.add(
                UserORM(
                    id=admin_id,
                    email=f"ops-{admin_id[:8]}@example.com",
                    password_hash="x",
                    display_name="运维",
                    status="active",
                    email_verified_at=datetime.now(UTC),
                )
            )
            session.add(
                UserRoleORM(id=str(uuid.uuid4()), user_id=admin_id, role="admin")
            )
            await session.commit()

        async with maker() as session:
            uow = SqlUnitOfWork(session)

            class _Principal:
                user_id = admin_id

            result = await support_operators(_Principal(), uow)  # type: ignore[arg-type]

        assert any(item["id"] == admin_id for item in result["items"])
    finally:
        async with maker() as session:
            await session.execute(
                sa.text("DELETE FROM user_roles WHERE user_id = :id"), {"id": admin_id}
            )
            await session.execute(sa.text("DELETE FROM users WHERE id = :id"), {"id": admin_id})
            await session.commit()
        await engine.dispose()

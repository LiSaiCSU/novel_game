from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.tenancy import set_tenant_context
from database.models.orm import WorldORM
from database.models.platform import ContentReleaseORM, PlaythroughORM, UserORM
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
    user_a, user_b, play_a, play_b, world_a, world_b = (str(uuid.uuid4()) for _ in range(6))

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

            result = await session.execute(
                sa.update(PlaythroughORM)
                .where(PlaythroughORM.id == play_b)
                .values(status="deleted")
            )
            assert result.rowcount == 0
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
            await session.execute(sa.delete(WorldORM).where(WorldORM.id.in_([world_a, world_b])))
            await session.execute(sa.delete(UserORM).where(UserORM.id.in_([user_a, user_b])))
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

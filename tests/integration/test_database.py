"""SQLAlchemy adapter tests (Phase 3).

Same world, same engine, different backend: an in-memory SQLite database
exercised through the real ORM, mappers and UnitOfWork.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.base import Base
from database.repositories.sql import SqlUnitOfWork
from database.seeding import persist_bundle
from engine.core.ids import PLAYER_KEY
from engine.core.types import KnowledgeState
from engine.orchestrator.turn import TurnRequest
from engine.world.state_view import build_world_state

pytestmark = pytest.mark.integration


@pytest.fixture
async def sql_session(bundle):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        await persist_bundle(session, bundle)
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
def sql_uow(sql_session) -> SqlUnitOfWork:
    return SqlUnitOfWork(sql_session)


async def test_seeded_world_round_trips(sql_uow, bundle, pack) -> None:
    world = await sql_uow.worlds.get(bundle.world.id)
    assert world is not None
    assert world.name == bundle.world.name
    assert world.current_minute == bundle.world.current_minute

    locations = await sql_uow.locations.list_for_world(world.id)
    assert len(locations) == len(pack.locations)

    characters = await sql_uow.characters.list_for_world(world.id, alive_only=False)
    assert len(characters) == len(bundle.characters)


async def test_character_structure_survives_the_round_trip(sql_uow, bundle) -> None:
    """Prompt section 12: personality and emotion are structured, not prose."""
    source = next(c for c in bundle.characters if c.personality.traits)
    loaded = await sql_uow.characters.get(source.id)
    assert loaded is not None
    assert loaded.personality.traits == source.personality.traits
    assert loaded.personality.values == source.personality.values
    assert loaded.current_emotion.dominant == source.current_emotion.dominant
    assert loaded.schedule.slots and len(loaded.schedule.slots) == len(source.schedule.slots)
    assert loaded.reputation.by_faction == source.reputation.by_faction


async def test_knowledge_firewall_holds_in_sql(sql_uow, bundle, pack) -> None:
    """list_known() filters UNKNOWN in SQL, not just in Python."""
    secret = next(
        f for f in pack.facts if f.get("sensitivity", 0) >= 0.9 and f.get("initial_knowledge")
    )
    ignorant = next(
        c
        for c in bundle.characters
        if c.key not in secret["initial_knowledge"] and c.key != PLAYER_KEY
    )
    rows = await sql_uow.knowledge.list_known(ignorant.id)
    assert all(k.knowledge_state is not KnowledgeState.UNKNOWN for k, _ in rows)
    assert all(fact.key != secret["key"] for _k, fact in rows)


async def test_world_state_builds_from_sql(sql_uow, pack, bundle) -> None:
    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    state = await build_world_state(sql_uow, pack, bundle.world.id, player.id)
    assert state.player.key == PLAYER_KEY
    assert state.location is not None
    assert state.graph.all()
    assert state.inventory


async def test_a_full_turn_runs_against_sql(sql_uow, orchestrator, bundle) -> None:
    """The same orchestrator, unchanged, on a real database."""
    assert bundle.session is not None
    result = await orchestrator.play_turn(
        sql_uow, TurnRequest(session_id=bundle.session.id, text="我打坐修炼一个时辰", debug=True)
    )
    assert result.narrative
    world = await sql_uow.worlds.get(bundle.world.id)
    assert world is not None
    assert world.current_minute > bundle.world.current_minute

    events = await sql_uow.events.list_recent(bundle.world.id, limit=10)
    assert any(e.event_type == "CULTIVATION_SESSION" for e in events)

    trace = await sql_uow.turns.get_trace(result.turn_id)
    assert trace is not None
    assert trace["stage_timings"]


async def test_event_repository_has_no_write_escape_hatch(sql_uow) -> None:
    assert not hasattr(sql_uow.events, "update")
    assert not hasattr(sql_uow.events, "delete")


async def test_inventory_removal_is_checked_against_reality(sql_uow, bundle) -> None:
    from engine.core.errors import EngineError
    from engine.core.mutations import ChangeSet, inventory_remove

    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    change_set = ChangeSet()
    change_set.add(inventory_remove(player.id, "spirit_stone", 10**9, reason="cheat"))
    with pytest.raises(EngineError):
        await sql_uow.apply(change_set)


async def test_rollback_leaves_the_world_untouched(sql_uow, bundle) -> None:
    from engine.core.mutations import ChangeSet, character_field

    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    before = (await sql_uow.characters.get(player.id)).health

    change_set = ChangeSet()
    change_set.add(character_field(player.id, "health", before, before - 30, reason="test"))
    await sql_uow.apply(change_set)
    await sql_uow.rollback()

    after = (await sql_uow.characters.get(player.id)).health
    assert after == before

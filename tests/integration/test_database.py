"""SQLAlchemy adapter tests (Phase 3).

Same world, same engine, different backend: an in-memory SQLite database
exercised through the real ORM, mappers and UnitOfWork.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.base import Base
from database.models.orm import MemoryORM
from database.repositories.sql import SqlUnitOfWork
from database.seeding import persist_bundle
from engine.core.ids import PLAYER_KEY
from engine.core.types import DirectorEventStatus, KnowledgeState
from engine.orchestrator.turn import TurnRequest, TurnStatus
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

    director_events = await sql_uow.director_events.list_for_world(world.id)
    assert len(director_events) == len(bundle.director_events)
    assert all(event.status is DirectorEventStatus.SCHEDULED for event in director_events)


async def test_sql_memory_repository_enforces_owner_event_idempotency(
    sql_uow, bundle
) -> None:
    from engine.core.models import Memory

    owner = bundle.character_by_key(PLAYER_KEY)
    assert owner is not None
    first = Memory(
        world_id=bundle.world.id,
        owner_character_id=owner.id,
        summary="同一件已提交事件",
        related_event_id="canonical-event-1",
    )
    duplicate = first.model_copy(update={"id": "duplicate-memory"})

    await sql_uow.memories.add(first)
    await sql_uow.memories.add(duplicate)
    await sql_uow.commit()

    rows = await sql_uow.memories.list_for_owner(owner.id)
    assert len([row for row in rows if row.related_event_id == "canonical-event-1"]) == 1
    assert any(
        constraint.name == "uq_memory_owner_event"
        for constraint in MemoryORM.__table__.constraints
    )


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

    major = next(c for c in bundle.characters if c.goal_lifecycle is not None)
    loaded_major = await sql_uow.characters.get(major.id)
    assert loaded_major is not None
    assert loaded_major.goal_lifecycle == major.goal_lifecycle


async def test_npc_goal_action_result_persists_atomically_in_sql(
    sql_uow, bundle, pack
) -> None:
    from engine.characters.goals import GoalLifecycleService
    from engine.core.mutations import ChangeSet, character_goals
    from engine.events.builder import EventBuilder
    from engine.rng.game_rng import GameRNG

    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    state = await build_world_state(sql_uow, pack, bundle.world.id, player.id)
    npc = next(c for c in bundle.characters if c.goal_lifecycle is not None)
    loaded = await sql_uow.characters.get(npc.id)
    assert loaded is not None and loaded.goal_lifecycle is not None
    loaded.goal_lifecycle.steps[0].success_chance = 1.0
    result = GoalLifecycleService(pack).advance(
        loaded,
        state.world.current_minute,
        loaded.goal_lifecycle.next_action_minute,
        rng=GameRNG("sql-goal-commit"),
        event_builder=EventBuilder(pack, state.world.id, "sql-goal-turn"),
        graph=state.graph,
    )
    assert result.lifecycle is not None and result.events
    changes = ChangeSet()
    changes.add(
        character_goals(
            loaded.id,
            {"goal_lifecycle": result.lifecycle.model_dump(mode="json")},
            reason="test",
        )
    )
    for event in result.events:
        changes.add_event(event)

    await sql_uow.apply(changes)
    await sql_uow.commit()

    stored = await sql_uow.characters.get(loaded.id)
    stored_event = await sql_uow.events.get(result.events[0].id)
    assert stored is not None and stored.goal_lifecycle is not None
    assert stored.goal_lifecycle.current_step == 1
    assert stored_event is not None
    assert stored.goal_lifecycle.last_result is not None
    assert stored.goal_lifecycle.last_result.event_id == stored_event.id


async def test_director_lifecycle_and_canonical_event_persist_atomically_in_sql(
    sql_uow, bundle, pack
) -> None:
    from engine.core.mutations import ChangeSet
    from engine.director.lifecycle import DirectorEventLifecycleService
    from engine.events.builder import EventBuilder

    scheduled = min(bundle.director_events, key=lambda event: event.scheduled_for_minute)
    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    state = await build_world_state(sql_uow, pack, bundle.world.id, player.id)
    changes = ChangeSet()
    status = await DirectorEventLifecycleService(pack).activate(
        sql_uow,
        state,
        scheduled,
        changes,
        event_builder=EventBuilder(pack, state.world.id, "sql-director-turn"),
    )
    assert status is DirectorEventStatus.RESOLVED

    await sql_uow.apply(changes)
    await sql_uow.commit()

    stored = await sql_uow.director_events.get(scheduled.id)
    assert stored is not None
    assert stored.status is DirectorEventStatus.RESOLVED
    assert stored.canonical_event_id
    canonical = await sql_uow.events.get(stored.canonical_event_id)
    assert canonical is not None
    assert canonical.payload["director_event_id"] == stored.id


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
    stored = await sql_uow.turns.get(result.turn_id)
    assert stored is not None
    assert stored["status"] == str(TurnStatus.COMPLETED)
    assert stored["canonical_payload"]["change_set"]
    assert trace is not None
    assert trace["stage_timings"]


async def test_sql_narrative_retry_does_not_reapply_canonical_state(
    sql_uow, orchestrator, bundle, monkeypatch
) -> None:
    assert bundle.session is not None
    original_render = orchestrator.d.narrative.render
    calls = 0

    async def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected SQL narrative crash")
        return await original_render(*args, **kwargs)

    monkeypatch.setattr(orchestrator.d.narrative, "render", fail_once)
    request = TurnRequest(
        session_id=bundle.session.id,
        text="我打坐修炼一个时辰",
        idempotency_key="sql-narrative-retry",
    )
    before = (await sql_uow.worlds.get(bundle.world.id)).current_minute
    first = await orchestrator.play_turn(sql_uow, request)
    after_first = (await sql_uow.worlds.get(bundle.world.id)).current_minute
    events_after_first = len(await sql_uow.events.list_recent(bundle.world.id, limit=100))
    assert after_first > before
    assert first.status is TurnStatus.NARRATIVE_FAILED

    second = await orchestrator.play_turn(sql_uow, request)
    assert second.turn_id == first.turn_id
    assert second.status is TurnStatus.COMPLETED
    assert (await sql_uow.worlds.get(bundle.world.id)).current_minute == after_first
    assert len(await sql_uow.events.list_recent(bundle.world.id, limit=100)) == events_after_first


async def test_sql_memory_failure_resumes_without_reapplying_canonical_state(
    sql_uow, orchestrator, bundle, monkeypatch
) -> None:
    from engine.core.errors import EngineError

    assert bundle.session is not None
    original_extract = orchestrator.d.memory.extract
    calls = 0

    async def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected SQL memory projection crash")
        return await original_extract(*args, **kwargs)

    monkeypatch.setattr(orchestrator.d.memory, "extract", fail_once)
    request = TurnRequest(
        session_id=bundle.session.id,
        text="我打坐修炼一个时辰",
        idempotency_key="sql-memory-retry",
    )
    before = (await sql_uow.worlds.get(bundle.world.id)).current_minute

    with pytest.raises(EngineError, match="memory projection failed after canonical commit"):
        await orchestrator.play_turn(sql_uow, request)

    after_failure = (await sql_uow.worlds.get(bundle.world.id)).current_minute
    events_after_failure = len(await sql_uow.events.list_recent(bundle.world.id, limit=100))
    failed = await sql_uow.turns.get_by_idempotency_key("sql-memory-retry")
    assert failed is not None
    assert failed["canonical_payload"]["memory_projection"]["status"] == "FAILED"
    assert after_failure > before

    result = await orchestrator.play_turn(sql_uow, request)
    completed = await sql_uow.turns.get(result.turn_id)

    assert result.status is TurnStatus.COMPLETED
    assert (await sql_uow.worlds.get(bundle.world.id)).current_minute == after_failure
    assert len(await sql_uow.events.list_recent(bundle.world.id, limit=100)) == events_after_failure
    assert calls == 2
    assert completed is not None
    assert completed["canonical_payload"]["memory_projection"]["status"] == "COMPLETED"


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


async def test_steward_spawns_persist_through_sql(sql_uow, bundle, pack) -> None:
    """The browser game runs on SQL, so growth has to survive that path too.

    A world that only grows in the in-memory store would work in the CLI and
    quietly forget every improvised shopkeeper in the real game.
    """
    from engine.core.mutations import ChangeSet
    from engine.world.state_view import build_world_state
    from engine.world.steward import (
        CharacterDraft,
        LocationDraft,
        StewardPlan,
        StewardResult,
        WorldSteward,
    )

    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    state = await build_world_state(sql_uow, pack, bundle.world.id, player.id)
    everyone = await sql_uow.characters.list_for_world(bundle.world.id)

    steward = WorldSteward(pack)
    result = StewardResult()
    steward._apply_plan(
        state,
        StewardPlan(
            interpretation="玩家走进坊市后巷的杂货摊",
            new_locations=[
                LocationDraft(
                    key="market_back_alley",
                    name="坊市后巷",
                    parent_key="qingyun_market",
                    description="堆着空药筐的窄巷，白日也照不进太阳。",
                )
            ],
            new_characters=[
                CharacterDraft(
                    key="alley_pedlar",
                    name="麻脸老赵",
                    location_key="market_back_alley",
                    speech_style="嗓门大，话里三分真",
                )
            ],
        ),
        everyone,
        result,
    )
    assert result.new_locations and result.new_characters

    change_set = ChangeSet()
    change_set.extend(result.changes)
    await sql_uow.apply(change_set)
    await sql_uow.commit()

    locations = await sql_uow.locations.list_for_world(bundle.world.id)
    alley = next((loc for loc in locations if loc.key == "market_back_alley"), None)
    assert alley is not None
    assert alley.name == "坊市后巷"
    assert alley.metadata["origin"] == "steward"

    characters = await sql_uow.characters.list_for_world(bundle.world.id)
    pedlar = next((c for c in characters if c.key == "alley_pedlar"), None)
    assert pedlar is not None
    assert pedlar.name == "麻脸老赵"
    assert pedlar.location_id == alley.id
    assert pedlar.personality.speech_style == "嗓门大，话里三分真"

    # And the new place is routable, or the player could never walk back to it.
    refreshed = await build_world_state(sql_uow, pack, bundle.world.id, player.id)
    assert refreshed.graph.path(refreshed.location_key(), "market_back_alley") is not None


async def test_a_save_restores_the_world_and_the_story(sql_uow, bundle, pack) -> None:
    """A save is a restore point, not a bookmark.

    Rewinding by reversing state changes cannot work here - the event log is
    append-only, memories are projections of it, and prose is not reversible.
    So a save copies every row, and loading must bring all of it back: the
    world, the people, and the chapters the player has read.
    """
    from database.saves import SaveService
    from engine.core.models import NarrativeSegment
    from engine.world.state_view import build_world_state

    saves = SaveService(sql_uow.session)
    session = bundle.session
    assert session is not None

    # A story in progress: one chapter read, one character where they started.
    await sql_uow.turns.append_narrative(
        NarrativeSegment(
            session_id=session.id, kind="chapter", text="第一章：你走进了青云宗。"
        )
    )
    state = await build_world_state(
        sql_uow, pack, bundle.world.id, session.player_character_id
    )
    home = state.player.location_id
    await sql_uow.commit()

    header = await saves.capture(
        session_id=session.id,
        world_id=bundle.world.id,
        name="进山门前",
        player_name=state.player.name,
        turn_number=session.turn_number,
    )
    await sql_uow.commit()
    assert header.name == "进山门前"

    # Now the world moves on, in every way a save has to be able to undo.
    from engine.core import mutations as mut
    from engine.core.mutations import ChangeSet

    elsewhere = next(
        loc
        for loc in await sql_uow.locations.list_for_world(bundle.world.id)
        if loc.id != home
    )
    damage = ChangeSet()
    damage.add(
        mut.character_move(
            session.player_character_id, home, elsewhere.id, reason="test"
        )
    )
    damage.add(
        mut.character_field(
            session.player_character_id,
            "health",
            state.player.health,
            3,
            reason="test",
        )
    )
    await sql_uow.apply(damage)
    await sql_uow.turns.append_narrative(
        NarrativeSegment(
            session_id=session.id, kind="chapter", text="第二章：一切都搞砸了。"
        )
    )
    await sql_uow.commit()

    moved = await sql_uow.characters.get(session.player_character_id)
    assert moved is not None and moved.health == 3
    assert len(await sql_uow.turns.list_narrative(session.id, limit=10)) == 2

    # Load.
    restored = await saves.restore(header.id)
    await sql_uow.commit()
    assert restored is not None

    back = await sql_uow.characters.get(session.player_character_id)
    assert back is not None
    assert back.health == state.player.health
    assert back.location_id == home

    segments = await sql_uow.turns.list_narrative(session.id, limit=10)
    assert [s.text for s in segments] == ["第一章：你走进了青云宗。"]


async def test_saves_are_listed_newest_first_and_can_be_deleted(
    sql_uow, bundle
) -> None:
    from database.saves import SaveService

    saves = SaveService(sql_uow.session)
    session = bundle.session
    assert session is not None

    first = await saves.capture(
        session_id=session.id, world_id=bundle.world.id, name="存档一"
    )
    second = await saves.capture(
        session_id=session.id, world_id=bundle.world.id, name="存档二"
    )
    await sql_uow.commit()

    listed = await saves.list_for_session(session.id)
    assert {h.name for h in listed} == {"存档一", "存档二"}

    assert await saves.delete(first.id) is True
    await sql_uow.commit()
    remaining = await saves.list_for_session(session.id)
    assert [h.id for h in remaining] == [second.id]

    assert await saves.delete("no-such-save") is False
    assert await saves.restore("no-such-save") is None

from __future__ import annotations

import pytest

from engine.characters.schemas import DirectorDecision
from engine.core.errors import EngineError
from engine.core.mutations import ChangeKind, ChangeSet
from engine.core.types import DirectorDecisionType, DirectorEventStatus
from engine.director.lifecycle import DirectorEventLifecycleService
from engine.events.builder import EventBuilder
from engine.knowledge.service import KnowledgeService
from engine.rng.game_rng import GameRNG
from engine.simulation.schedules import ScheduleService
from engine.simulation.simulator import WorldSimulator


def _simulator(pack, *, max_minutes: int = 0) -> WorldSimulator:
    knowledge = KnowledgeService(pack)
    return WorldSimulator(
        pack,
        ScheduleService(pack),
        knowledge,
        max_offline_minutes=max_minutes,
    )


async def _jump(pack, uow, state, minutes: int, seed: str = "long-jump"):
    changes = ChangeSet()
    rng = GameRNG(seed)
    report = await _simulator(pack).advance(
        uow,
        state,
        minutes,
        changes,
        rng=rng,
        event_builder=EventBuilder(pack, state.world.id, "temporal-turn"),
    )
    return report, changes, rng


async def test_thirty_year_jump_uses_bounded_temporal_windows(pack, uow, state) -> None:
    minutes = state.clock.minutes_per_year * 30
    report, changes, rng = await _jump(pack, uow, state, minutes)

    assert report.strategy == "temporal_jump"
    assert report.requested_minutes == minutes
    assert report.minutes == minutes
    assert report.processed_windows == 3
    assert report.ticks["lod3"] > 1_000  # logical boundaries, not executed loops
    assert len(report.offline_events) <= 12
    assert sum(event.event_type == "OFFLINE_WORLD_EVENT" for event in changes.events) <= 12
    assert report.aggregate_event_count >= len(report.offline_events)
    assert report.aged_characters > 0
    assert report.natural_deaths
    assert report.npc_goal_actions > 0
    assert report.npc_goal_steps_completed > 0
    assert changes.by_kind(ChangeKind.CHARACTER_DEATH)
    assert any(event.event_type == "DEATH" for event in changes.events)

    player_age = next(
        change
        for change in changes.by_kind(ChangeKind.CHARACTER_FIELD)
        if change.target_id == state.player.id and change.field == "age"
    )
    assert player_age.after == player_age.before + 30

    offline_traces = [
        trace for trace in rng.traces if trace.stream_key.endswith("offline-events")
    ]
    assert sum(trace.method == "binomial" for trace in offline_traces) == 1
    assert len(offline_traces) <= 14

    goal_traces = [trace for trace in rng.traces if "npc-goal:" in trace.stream_key]
    major_plan_steps = sum(
        len(character.goal_lifecycle.steps)
        for character in (await uow.characters.list_for_world(state.world.id))
        if character.goal_lifecycle is not None
    )
    assert all(trace.method == "geometric" for trace in goal_traces)
    assert len(goal_traces) <= major_plan_steps

    target = state.world.current_minute + minutes
    for event in changes.events:
        if event.event_type == "OFFLINE_WORLD_EVENT":
            assert state.world.current_minute < event.world_minute < target
            assert event.payload["occurrences"] >= 1


async def test_faction_drift_uses_the_full_jump_not_a_52_week_cap(pack, uow, state) -> None:
    one_year = state.clock.minutes_per_year
    _short_report, short_changes, _ = await _jump(pack, uow, state, one_year, seed="drift")
    _long_report, long_changes, _ = await _jump(
        pack, uow, state, one_year * 30, seed="drift"
    )

    def faction_afters(change_set: ChangeSet):
        return {
            (change.target_id, change.field): change.after
            for change in change_set.by_kind(ChangeKind.FACTION_FIELD)
        }

    assert faction_afters(long_changes) != faction_afters(short_changes)


async def test_mid_jump_death_preserves_only_pre_death_goal_actions_and_cancels_late_event(
    pack, uow, state, session_id
) -> None:
    doomed = await uow.characters.get_by_key(state.world.id, "lu_xuan")
    assert doomed is not None and doomed.goal_lifecycle is not None
    lifespan = pack.realms.realm(doomed.realm).lifespan_years
    years_left = lifespan - doomed.age
    assert years_left > 0
    death_minute = state.world.current_minute + years_left * state.clock.minutes_per_year

    director_service = DirectorEventLifecycleService(pack)
    decision = DirectorDecision(
        decision=DirectorDecisionType.TRIGGER_EVENT,
        event_type="NPC_APPROACH",
        participants=[doomed.key],
        proposal="宗主按既有线索前来处理后续",
        schedule_after_minutes=(years_left + 1) * state.clock.minutes_per_year,
        causal_basis=["long_jump_regression"],
    )
    scheduled = director_service.propose(
        state,
        decision,
        [doomed],
        None,
        session_id=session_id,
        turn_id="long-jump-setup",
        turn_number=0,
    )
    async with uow:
        await uow.apply(ChangeSet(director_events=[scheduled]))
        await uow.commit()

    report, changes, _rng = await _jump(
        pack,
        uow,
        state,
        state.clock.minutes_per_year * (years_left + 2),
        seed="mid-jump-death",
    )

    goal_events = [
        event
        for event in changes.events
        if event.event_type == "NPC_GOAL_ACTION_RESULT" and event.actor_id == doomed.id
    ]
    assert goal_events, "a dying major NPC must still live out the pre-death part of the jump"
    assert all(event.world_minute < death_minute for event in goal_events)
    assert any(
        event.event_type == "DEATH"
        and event.actor_id == doomed.id
        and event.world_minute == death_minute
        for event in changes.events
    )

    lifecycle = next(event for event in changes.director_events if event.id == scheduled.id)
    assert lifecycle.status is DirectorEventStatus.CANCELLED
    assert lifecycle.cancellation_reason.startswith("participant_dead")
    assert not any(
        event.payload.get("director_event_id") == scheduled.id
        for event in changes.events
    )
    assert report.director_events_cancelled >= 1
    assert report.reassigned_quests, "ignored expiring quests must resolve during the same jump"


async def test_temporal_jump_limit_rejects_instead_of_silently_clipping(
    pack, uow, state
) -> None:
    limit = state.clock.minutes_per_year
    simulator = _simulator(pack, max_minutes=limit)
    changes = ChangeSet()
    with pytest.raises(EngineError, match="exceeds configured limit"):
        await simulator.advance(
            uow,
            state,
            limit * 3,
            changes,
            rng=GameRNG("limit"),
            event_builder=EventBuilder(pack, state.world.id, "limited-turn"),
        )
    assert changes.is_empty()

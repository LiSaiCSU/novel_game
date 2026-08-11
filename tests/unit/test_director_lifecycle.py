from __future__ import annotations

from engine.characters.schemas import DirectorDecision
from engine.core.models import DirectorEvent
from engine.core.mutations import ChangeKind, ChangeSet
from engine.core.types import (
    DirectorDecisionType,
    DirectorEventStatus,
)
from engine.director.lifecycle import DirectorEventLifecycleService
from engine.director.validator import DirectorValidator
from engine.events.builder import EventBuilder
from engine.knowledge.service import KnowledgeService
from engine.rng.game_rng import GameRNG
from engine.simulation.schedules import ScheduleService
from engine.simulation.simulator import WorldSimulator


def _decision(participant_key: str, *, delay: int = 0) -> DirectorDecision:
    return DirectorDecision(
        decision=DirectorDecisionType.TRIGGER_EVENT,
        event_type="NPC_APPROACH",
        participants=[participant_key],
        proposal="有人循着既有线索来到此处",
        schedule_after_minutes=delay,
        tension_delta=4.0,
    )


def test_content_scheduled_beats_are_seeded_as_canonical_lifecycles(bundle) -> None:
    declared = sum(
        len(thread.metadata.get("scheduled_beats", []) or [])
        for thread in bundle.plot_threads
    )
    assert len(bundle.director_events) == declared == 4
    assert all(event.status is DirectorEventStatus.SCHEDULED for event in bundle.director_events)
    assert all(
        [transition.status for transition in event.history]
        == [DirectorEventStatus.PROPOSED, DirectorEventStatus.SCHEDULED]
        for event in bundle.director_events
    )
    assert bundle.director_events[0].scheduled_for_minute < bundle.director_events[1].scheduled_for_minute


async def test_immediate_director_event_records_full_lifecycle(pack, uow, state, session_id) -> None:
    participant = state.present_characters[0]
    service = DirectorEventLifecycleService(pack)
    root_event = EventBuilder(pack, state.world.id, "root-turn").build(
        "OBSERVATION", actor_id=state.player.id, world_minute=state.world.current_minute
    )
    await uow.events.append(root_event)
    decision = _decision(participant.key)
    decision.causal_basis = [root_event.id, "existing_fact_basis"]
    record = service.propose(
        state,
        decision,
        [participant],
        None,
        session_id=session_id,
        turn_id="director-turn",
        turn_number=1,
    )
    changes = ChangeSet()
    status = await service.activate(
        uow,
        state,
        record,
        changes,
        event_builder=EventBuilder(pack, state.world.id, "director-turn"),
    )

    assert status is DirectorEventStatus.RESOLVED
    assert len(changes.director_events) == 1
    resolved = DirectorEvent.model_validate(
        changes.director_events[0].model_dump(mode="json")
    )
    assert [transition.status for transition in resolved.history] == [
        DirectorEventStatus.PROPOSED,
        DirectorEventStatus.SCHEDULED,
        DirectorEventStatus.ACTIVE,
        DirectorEventStatus.RESOLVED,
    ]
    assert len(changes.events) == 1
    assert resolved.canonical_event_id == changes.events[0].id
    assert changes.events[0].payload["director_event_id"] == resolved.id
    assert changes.events[0].cause_event_ids == [root_event.id]
    assert changes.events[0].causes == ["existing_fact_basis"]


async def test_validator_rejects_same_causal_beat_after_it_is_recorded(
    pack, uow, state, session_id
) -> None:
    participant = state.present_characters[0]
    decision = _decision(participant.key, delay=60)
    service = DirectorEventLifecycleService(pack)
    record = service.propose(
        state,
        decision,
        [participant],
        None,
        session_id=session_id,
        turn_id="scheduled-turn",
        turn_number=1,
    )
    changes = ChangeSet(director_events=[record])
    async with uow:
        await uow.apply(changes)
        await uow.commit()

    outcome = await DirectorValidator(pack).validate(uow, state, decision)
    assert not outcome.accepted
    assert any(reason.startswith("duplicate_director_event") for reason in outcome.rejections)

    due_changes = ChangeSet()
    due = await service.process_due(
        uow,
        state,
        state.world.current_minute + 60,
        due_changes,
        event_builder=EventBuilder(pack, state.world.id, "due-turn"),
    )
    assert due.resolved == 1
    assert due.tension_delta == decision.tension_delta


async def test_due_event_is_cancelled_if_participant_died(
    pack, uow, state, store, session_id
) -> None:
    participant = state.present_characters[0]
    service = DirectorEventLifecycleService(pack)
    record = service.propose(
        state,
        _decision(participant.key, delay=60),
        [participant],
        None,
        session_id=session_id,
        turn_id="scheduled-turn",
        turn_number=1,
    )
    async with uow:
        await uow.apply(ChangeSet(director_events=[record]))
        await uow.commit()
    store.characters[participant.id].alive = False

    due_changes = ChangeSet()
    report = await service.process_due(
        uow,
        state,
        state.world.current_minute + 60,
        due_changes,
        event_builder=EventBuilder(pack, state.world.id, "due-turn"),
    )

    assert report.cancelled == 1
    assert report.resolved == 0
    assert not due_changes.events
    cancelled = DirectorEvent.model_validate(
        due_changes.director_events[0].model_dump(mode="json")
    )
    assert cancelled.status is DirectorEventStatus.CANCELLED
    assert cancelled.cancellation_reason.startswith("participant_dead")
    assert report.tension_delta == 0.0


async def test_temporal_jump_resolves_sequential_content_beats_without_ticks(
    pack, uow, state
) -> None:
    thread = await uow.plot_threads.get_by_key(
        state.world.id, "thread_seven_day_blood_contract"
    )
    assert thread is not None
    changes = ChangeSet()
    simulator = WorldSimulator(pack, ScheduleService(pack), KnowledgeService(pack))
    report = await simulator.advance(
        uow,
        state,
        10_080,
        changes,
        rng=GameRNG("scheduled-beats"),
        event_builder=EventBuilder(pack, state.world.id, "jump-turn"),
    )

    assert report.director_events_resolved == 4
    assert report.director_events_cancelled == 0
    assert report.director_tension_delta == 0.0  # seeded beats do not force tension
    resolved = [
        event for event in changes.director_events if event.status is DirectorEventStatus.RESOLVED
    ]
    assert len(resolved) == 4
    assert all(
        len(event.history) == 4 and event.canonical_event_id
        for event in resolved
    )
    thread_changes = [
        change
        for change in changes.by_kind(ChangeKind.PLOT_THREAD_UPDATE)
        if change.target_id == thread.id
    ]
    assert [change.payload["stage"] for change in thread_changes] == [
        thread.stage + offset for offset in range(1, 5)
    ]


async def test_due_events_over_daily_cap_are_rescheduled_without_day_ticks(
    pack, uow, state, store, session_id
) -> None:
    participant = state.present_characters[0]
    service = DirectorEventLifecycleService(pack)
    # Pin the cap here rather than inheriting the pack's. This test is about
    # the overflow mechanism, not about how eventful the shipped world is -
    # tuning the content pack should never make it silently stop testing it.
    service.max_events_per_day = 2
    # This test owns its schedule; shipped story obligations are covered by
    # the preceding tests and must not affect the aggregate report here.
    store.director_events.clear()
    scheduled = []
    for index in range(3):
        decision = _decision(participant.key, delay=60)
        decision.causal_basis = [f"test_cause_{index}"]
        scheduled.append(
            service.propose(
                state,
                decision,
                [participant],
                None,
                session_id=session_id,
                turn_id=f"schedule-{index}",
                turn_number=index + 1,
            )
        )
    async with uow:
        await uow.apply(ChangeSet(director_events=scheduled))
        await uow.commit()

    changes = ChangeSet()
    report = await service.process_due(
        uow,
        state,
        state.world.current_minute + state.clock.minutes_per_day + 60,
        changes,
        event_builder=EventBuilder(pack, state.world.id, "due-cap-turn"),
    )

    assert report.resolved == 3
    assert report.rescheduled == 1
    resolved_minutes = sorted(
        event.scheduled_for_minute
        for event in changes.director_events
        if event.status is DirectorEventStatus.RESOLVED
    )
    assert resolved_minutes == [
        state.world.current_minute + 60,
        state.world.current_minute + 60,
        state.world.current_minute + state.clock.minutes_per_day + 60,
    ]

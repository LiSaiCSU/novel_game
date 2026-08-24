from __future__ import annotations

from engine.characters.goals import GoalLifecycleService
from engine.characters.npc_agent import NPCDecisionResult
from engine.characters.schemas import NPCDecision, NPCDecisionBody
from engine.core.mutations import ChangeKind, ChangeSet, character_goals
from engine.core.types import ActionType, CharacterType, GoalActionOutcome, GoalStatus
from engine.events.builder import EventBuilder
from engine.orchestrator.proposals import ProposalValidator
from engine.relationships.manager import RelationshipManager
from engine.rng.game_rng import GameRNG


class _AlwaysFailGoalRng(GameRNG):
    """A deterministic boundary double: a 1% roll can still succeed."""

    def derive(self, key: str) -> _AlwaysFailGoalRng:
        return self

    def geometric(self, probability: float, max_trials: int) -> int | None:
        return None


def _major(store):
    return next(
        character
        for character in store.characters.values()
        if character.character_type is CharacterType.MAJOR_NPC
    )


def test_major_npc_seed_has_durable_goal_plan(store) -> None:
    npc = _major(store)
    lifecycle = npc.goal_lifecycle
    assert lifecycle is not None
    assert lifecycle.goal == npc.long_term_goal
    assert [step.description for step in lifecycle.steps] == npc.short_term_goals
    assert lifecycle.status is GoalStatus.ACTIVE
    assert lifecycle.current_plan_step is lifecycle.steps[0]

    non_major = next(
        character
        for character in store.characters.values()
        if character.character_type is CharacterType.BACKGROUND
    )
    assert non_major.goal_lifecycle is None


def test_goal_advance_records_canonical_action_result_without_ticks(pack, store, state) -> None:
    npc = _major(store)
    lifecycle = npc.goal_lifecycle
    assert lifecycle is not None
    lifecycle.steps[0].success_chance = 1.0
    target = lifecycle.next_action_minute

    result = GoalLifecycleService(pack).advance(
        npc,
        state.world.current_minute,
        target,
        rng=GameRNG("npc-success"),
        event_builder=EventBuilder(pack, state.world.id, "goal-turn"),
        graph=state.graph,
    )

    assert result.changed
    assert result.attempts == 1
    assert result.completed_steps == 1
    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_type == "NPC_GOAL_ACTION_RESULT"
    assert event.payload["outcome"] == str(GoalActionOutcome.SUCCEEDED)
    assert event.actor_id == npc.id
    assert result.lifecycle is not None
    assert result.lifecycle.last_result is not None
    assert result.lifecycle.last_result.event_id == event.id


async def test_goal_state_and_result_commit_atomically_in_memory(
    pack, store, state, uow
) -> None:
    npc = _major(store)
    assert npc.goal_lifecycle is not None
    npc.goal_lifecycle.steps[0].success_chance = 1.0
    result = GoalLifecycleService(pack).advance(
        npc,
        state.world.current_minute,
        npc.goal_lifecycle.next_action_minute,
        rng=GameRNG("memory-goal-commit"),
        event_builder=EventBuilder(pack, state.world.id, "goal-turn"),
        graph=state.graph,
    )
    assert result.lifecycle is not None
    changes = ChangeSet()
    changes.add(
        character_goals(
            npc.id,
            {"goal_lifecycle": result.lifecycle.model_dump(mode="json")},
            reason="test",
        )
    )
    for event in result.events:
        changes.add_event(event)

    async with uow:
        await uow.apply(changes)
        await uow.commit()

    stored = await uow.characters.get(npc.id)
    assert stored is not None and stored.goal_lifecycle is not None
    assert stored.goal_lifecycle.current_step == 1
    stored_event = await uow.events.get(result.events[0].id)
    assert stored_event is not None
    assert stored.goal_lifecycle.last_result is not None
    assert stored.goal_lifecycle.last_result.event_id == stored_event.id


def test_failed_attempt_stays_on_same_plan_step(pack, store, state) -> None:
    npc = _major(store)
    lifecycle = npc.goal_lifecycle
    assert lifecycle is not None
    lifecycle.steps[0].success_chance = 0.01
    before_step = lifecycle.current_step

    result = GoalLifecycleService(pack).advance(
        npc,
        state.world.current_minute,
        lifecycle.next_action_minute,
        rng=_AlwaysFailGoalRng("forced-failure"),
        event_builder=EventBuilder(pack, state.world.id, "goal-turn"),
        graph=state.graph,
    )

    assert result.lifecycle is not None
    assert result.lifecycle.last_result is not None
    assert result.lifecycle.last_result.outcome is GoalActionOutcome.FAILED
    assert result.lifecycle.current_step == before_step
    assert result.lifecycle.next_action_minute > lifecycle.next_action_minute


def test_dead_major_npc_cannot_advance_goal(pack, store, state) -> None:
    npc = _major(store)
    lifecycle = npc.goal_lifecycle
    assert lifecycle is not None
    npc.alive = False
    npc.goal_lifecycle = None  # legacy row must not be initialized after death

    result = GoalLifecycleService(pack).advance(
        npc,
        state.world.current_minute,
        lifecycle.next_action_minute * 10,
        rng=GameRNG("dead-goal"),
        event_builder=EventBuilder(pack, state.world.id, "goal-turn"),
        graph=state.graph,
    )

    assert not result.changed
    assert result.lifecycle is None
    assert result.events == []
    assert result.attempts == 0


async def test_validated_ai_goal_update_creates_new_plan_revision(
    pack, uow, state, store
) -> None:
    npc = _major(store)
    assert npc.goal_lifecycle is not None
    old_revision = npc.goal_lifecycle.revision
    validator = ProposalValidator(pack, RelationshipManager(pack))
    change_set = ChangeSet()
    decision = NPCDecisionResult(
        npc_id=npc.id,
        npc_key=npc.key,
        degraded=False,
        decision=NPCDecision(
            decision=NPCDecisionBody(action_type=str(ActionType.WAIT)),
            goal_update_proposal={
                "short_term_goals": ["核对新证据", "", "寻找可靠证人"]
            },
        ),
    )

    report = await validator.apply_npc_decision(
        uow,
        state,
        decision,
        change_set,
        importance=0.2,
        available_actions=[str(ActionType.WAIT)],
    )

    goal_change = change_set.by_kind(ChangeKind.CHARACTER_GOALS)[0]
    lifecycle = goal_change.payload["goal_lifecycle"]
    assert report.accepted and f"goals:{npc.key}" in report.accepted
    assert goal_change.payload["short_term_goals"] == ["核对新证据", "寻找可靠证人"]
    assert lifecycle["revision"] == old_revision + 1
    assert [step["description"] for step in lifecycle["steps"]] == [
        "核对新证据",
        "寻找可靠证人",
    ]

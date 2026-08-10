"""Persistent important-NPC goal lifecycles.

The service never invents domain consequences.  It turns an existing long-term
goal and its short-term plan into bounded, deterministic action attempts and
canonical result events.  A content Rule Plugin may later consume those events
to implement setting-specific consequences.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.contentpack.pack import ContentPack
from engine.core.ids import new_id
from engine.core.models import (
    Character,
    Event,
    NPCGoalLifecycle,
    NPCGoalPlanStep,
    NPCGoalResult,
)
from engine.core.types import (
    Activity,
    CharacterType,
    GoalActionOutcome,
    GoalStatus,
    GoalStepStatus,
    Visibility,
)
from engine.events.builder import EventBuilder
from engine.rng.game_rng import GameRNG
from engine.world.location_graph import LocationGraph


@dataclass(slots=True)
class GoalAdvanceResult:
    lifecycle: NPCGoalLifecycle | None
    changed: bool = False
    events: list[Event] = field(default_factory=list)
    attempts: int = 0
    completed_steps: int = 0


class GoalLifecycleService:
    """Build and advance canonical agendas without per-tick simulation."""

    def __init__(self, pack: ContentPack) -> None:
        self.pack = pack
        self.default_interval = max(
            1, int(pack.rule("simulation.npc_goal_action_interval_minutes", 10080))
        )

    def build(
        self,
        character: Character,
        at_minute: int,
        *,
        short_term_goals: list[str] | None = None,
        revision: int = 1,
        lifecycle_id: str | None = None,
    ) -> NPCGoalLifecycle | None:
        """Turn validated character goals into a durable executable plan."""
        if character.character_type is not CharacterType.MAJOR_NPC:
            return None
        descriptions = [
            str(goal).strip()[:120]
            for goal in (
                character.short_term_goals if short_term_goals is None else short_term_goals
            )
            if str(goal).strip()
        ][:5]
        if not character.long_term_goal.strip() or not descriptions:
            return None

        candidates = [
            slot
            for slot in character.schedule.slots
            if slot.activity in (Activity.INVESTIGATE, Activity.TRAVEL)
            and slot.location_key
        ]
        if not candidates:
            candidates = [
                slot
                for slot in character.schedule.slots
                if slot.activity is not Activity.SLEEP and slot.location_key
            ]
        chance = max(
            0.35,
            min(0.9, 0.45 + character.mental_state * 0.2 + character.intelligence / 200.0),
        )
        steps: list[NPCGoalPlanStep] = []
        for index, description in enumerate(descriptions):
            slot = candidates[index % len(candidates)] if candidates else None
            steps.append(
                NPCGoalPlanStep(
                    key=f"step_{index + 1}",
                    description=description,
                    activity=slot.activity if slot else character.schedule.default,
                    destination_key=slot.location_key if slot else character.location_key,
                    success_chance=round(chance, 3),
                )
            )
        return NPCGoalLifecycle(
            id=lifecycle_id or new_id(),
            goal=character.long_term_goal.strip()[:240],
            revision=revision,
            steps=steps,
            next_action_minute=at_minute + self.default_interval,
            action_interval_minutes=self.default_interval,
            created_at_minute=at_minute,
            updated_at_minute=at_minute,
        )

    def replan(
        self, character: Character, short_term_goals: list[str], at_minute: int
    ) -> NPCGoalLifecycle | None:
        previous = character.goal_lifecycle
        return self.build(
            character,
            at_minute,
            short_term_goals=short_term_goals,
            revision=(previous.revision + 1) if previous else 1,
            lifecycle_id=previous.id if previous else None,
        )

    def advance(
        self,
        character: Character,
        start_minute: int,
        target_minute: int,
        *,
        rng: GameRNG,
        event_builder: EventBuilder,
        graph: LocationGraph,
    ) -> GoalAdvanceResult:
        original = character.goal_lifecycle
        if not character.alive:
            return GoalAdvanceResult(lifecycle=original)
        lifecycle = (
            original.model_copy(deep=True)
            if original is not None
            else self.build(character, start_minute)
        )
        result = GoalAdvanceResult(
            lifecycle=lifecycle,
            changed=original is None and lifecycle is not None,
        )
        if (
            lifecycle is None
            or lifecycle.status is not GoalStatus.ACTIVE
        ):
            return result

        while lifecycle.current_plan_step is not None:
            step = lifecycle.current_plan_step
            assert step is not None
            if lifecycle.next_action_minute > target_minute:
                break
            available = (
                (target_minute - lifecycle.next_action_minute)
                // lifecycle.action_interval_minutes
                + 1
            )
            step_rng = rng.derive(
                f"npc-goal:{character.id}:{lifecycle.id}:r{lifecycle.revision}:"
                f"{step.key}:a{step.attempts}"
            )
            successful_trial = step_rng.geometric(step.success_chance, available)
            used = successful_trial or available
            action_minute = lifecycle.next_action_minute + (
                used - 1
            ) * lifecycle.action_interval_minutes
            step.attempts += used
            lifecycle.actions_attempted += used
            lifecycle.updated_at_minute = action_minute
            result.attempts += used

            succeeded = successful_trial is not None
            outcome = (
                GoalActionOutcome.SUCCEEDED if succeeded else GoalActionOutcome.FAILED
            )
            templates = self.pack.narrative_templates.get("npc_goal_action", {}) or {}
            template_key = "succeeded" if succeeded else "failed"
            template = str(templates.get(template_key, "{character}: {step}"))
            summary = template.format(
                character=character.display_name,
                step=step.description,
            )
            location = graph.by_key(step.destination_key) if step.destination_key else None
            event = event_builder.build(
                "NPC_GOAL_ACTION_RESULT",
                actor_id=character.id,
                location_id=location.id if location else character.location_id,
                payload={
                    "summary": summary,
                    "goal_id": lifecycle.id,
                    "goal": lifecycle.goal,
                    "plan_revision": lifecycle.revision,
                    "step_key": step.key,
                    "step": step.description,
                    "activity": str(step.activity),
                    "destination_key": step.destination_key,
                    "outcome": str(outcome),
                    "attempts": used,
                },
                causes=[f"goal:{lifecycle.id}", f"plan_revision:{lifecycle.revision}"],
                world_minute=action_minute,
                visibility=Visibility.PRIVATE,
            )
            result.events.append(event)
            lifecycle.last_result = NPCGoalResult(
                step_key=step.key,
                outcome=outcome,
                at_minute=action_minute,
                attempts=used,
                event_id=event.id,
                summary=summary,
            )
            lifecycle.next_action_minute = action_minute + lifecycle.action_interval_minutes
            result.changed = True

            if not succeeded:
                break
            step.status = GoalStepStatus.SUCCEEDED
            step.completed_at_minute = action_minute
            lifecycle.current_step += 1
            result.completed_steps += 1

        if lifecycle.current_step >= len(lifecycle.steps):
            lifecycle.status = GoalStatus.REVIEW_REQUIRED
            lifecycle.updated_at_minute = min(target_minute, lifecycle.updated_at_minute)
        return result

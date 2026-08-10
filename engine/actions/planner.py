"""Compile-time-safe execution of short multi-primitive player plans."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from engine.actions.resolver import ActionResolver
from engine.actions.schema import (
    Action,
    ActionOutcome,
    ActionPlan,
    ActionPrimitive,
    PredicateKind,
    RuleResult,
)
from engine.core.models import CharacterSkill, InventoryItem
from engine.core.mutations import ChangeKind, ChangeSet
from engine.core.types import ReasonCode
from engine.rules.base import RuleContext
from engine.rules.engine import RuleEngine
from engine.world.state_view import WorldStateView


@dataclass(slots=True)
class PlanResolution:
    rule_result: RuleResult
    outcome: ActionOutcome
    change_set: ChangeSet
    steps: list[dict[str, Any]]
    representative_action: Action


class ActionPlanExecutor:
    """Resolve all primitives into one guarded ChangeSet proposal.

    A rule rejection discards every earlier proposal. A resolved failure is a
    canonical attempted action and may cause later conditional steps to skip.
    """

    def __init__(
        self,
        rules: RuleEngine,
        resolver: ActionResolver,
        *,
        max_total_minutes: int = 1440,
    ) -> None:
        self.rules = rules
        self.resolver = resolver
        self.max_total_minutes = max(1, max_total_minutes)

    def execute(self, ctx: RuleContext, plan: ActionPlan) -> PlanResolution:
        projected = _copy_state(ctx.state)
        combined = ChangeSet()
        steps: list[dict[str, Any]] = []
        outcomes: dict[str, ActionOutcome] = {}
        elapsed = 0
        previous_event_ids: list[str] = []
        representative_action = plan.primitives[0].action

        for primitive in plan.primitives:
            if not self._condition_met(primitive, projected, outcomes):
                steps.append(
                    {
                        "primitive_id": primitive.primitive_id,
                        "action_type": str(primitive.action.action_type),
                        "status": "SKIPPED_CONDITION",
                    }
                )
                continue

            step_ctx = RuleContext(
                pack=ctx.pack,
                state=projected,
                rng=ctx.rng.derive(f"primitive:{primitive.primitive_id}"),
            )
            verdict = self.rules.validate_action(step_ctx, primitive.action)
            if not verdict.allowed:
                return self._reject(ctx, primitive, verdict, steps)

            outcome, changes = self.resolver.resolve(step_ctx, primitive.action, verdict)
            if elapsed + outcome.time_cost_minutes > self.max_total_minutes:
                verdict = RuleResult.deny(
                    ReasonCode.TIME_LIMIT_EXCEEDED,
                    "action plan exceeds the short-plan time limit",
                    primitive_id=primitive.primitive_id,
                    requested=elapsed + outcome.time_cost_minutes,
                    cap=self.max_total_minutes,
                )
                return self._reject(ctx, primitive, verdict, steps)

            for event in changes.events:
                event.payload = {**event.payload, "primitive_id": primitive.primitive_id}
                event.cause_event_ids = list(
                    dict.fromkeys([*event.cause_event_ids, *previous_event_ids])
                )
            current_event_ids = [event.id for event in changes.events]
            if current_event_ids:
                previous_event_ids = current_event_ids

            _merge(combined, changes)
            representative_action = primitive.action
            elapsed += outcome.time_cost_minutes
            outcomes[primitive.primitive_id] = outcome
            steps.append(
                {
                    "primitive_id": primitive.primitive_id,
                    "action_type": str(primitive.action.action_type),
                    "status": "RESOLVED",
                    "success": outcome.success,
                    "summary_key": outcome.summary_key,
                    "time_cost_minutes": outcome.time_cost_minutes,
                    "facts": outcome.facts,
                    "event_ids": current_event_ids,
                }
            )
            projected = _project(projected, changes, outcome.time_cost_minutes)

        executed = list(outcomes.values())
        outcome = ActionOutcome(
            action_type=plan.primitives[0].action.action_type,
            success=bool(executed) and all(item.success for item in executed),
            summary_key="ACTION_PLAN",
            time_cost_minutes=elapsed,
            facts={"primitive_results": steps},
            importance=max((item.importance for item in executed), default=0.02),
        )
        return PlanResolution(
            rule_result=RuleResult.ok(action_plan=True, primitive_count=len(plan.primitives)),
            outcome=outcome,
            change_set=combined,
            steps=steps,
            representative_action=representative_action,
        )

    def _reject(
        self,
        ctx: RuleContext,
        primitive: ActionPrimitive,
        verdict: RuleResult,
        prior_steps: list[dict[str, Any]],
    ) -> PlanResolution:
        outcome, rejected = self.resolver.resolve(ctx, primitive.action, verdict)
        discarded_steps = [
            {
                **step,
                "status": (
                    "DISCARDED" if step.get("status") == "RESOLVED" else step.get("status")
                ),
            }
            for step in prior_steps
        ]
        details = {
            **verdict.details,
            "primitive_id": primitive.primitive_id,
            "discarded_primitives": [
                step["primitive_id"]
                for step in discarded_steps
                if step.get("status") == "DISCARDED"
            ],
        }
        aggregate = RuleResult.deny(verdict.reason_code, verdict.reason, **details)
        outcome.facts = {**outcome.facts, **details}
        if rejected.events:
            rejected.events[0].payload = {
                **rejected.events[0].payload,
                "primitive_id": primitive.primitive_id,
                "discarded_primitives": details["discarded_primitives"],
            }
        return PlanResolution(
            rule_result=aggregate,
            outcome=outcome,
            change_set=rejected,
            steps=[
                *discarded_steps,
                {
                    "primitive_id": primitive.primitive_id,
                    "action_type": str(primitive.action.action_type),
                    "status": "REJECTED",
                    "reason_code": str(verdict.reason_code),
                },
            ],
            representative_action=primitive.action,
        )

    @staticmethod
    def _condition_met(
        primitive: ActionPrimitive,
        state: WorldStateView,
        outcomes: dict[str, ActionOutcome],
    ) -> bool:
        condition = primitive.condition
        if condition is None:
            return True
        if condition.kind is PredicateKind.PREVIOUS_SUCCEEDED:
            outcome = outcomes.get(condition.primitive_id or "")
            return outcome is not None and outcome.success
        if condition.kind is PredicateKind.HAS_ITEM:
            item_key = condition.item_key
            return item_key is not None and state.inventory_quantity(item_key) > 0
        if condition.kind is PredicateKind.TARGET_PRESENT:
            target_id = condition.target_id
            target = state.character_by_id(target_id)
            return target is not None and target.alive and state.is_present(target.id)
        if condition.kind is PredicateKind.AT_LOCATION:
            return bool(condition.location_key) and state.location_key() == condition.location_key
        return False


def _copy_state(state: WorldStateView) -> WorldStateView:
    return replace(
        state,
        world=state.world.model_copy(deep=True),
        player=state.player.model_copy(deep=True),
        location=state.location.model_copy(deep=True) if state.location else None,
        present_characters=[c.model_copy(deep=True) for c in state.present_characters],
        factions={key: value.model_copy(deep=True) for key, value in state.factions.items()},
        inventory=[row.model_copy(deep=True) for row in state.inventory],
        known_skills=[row.model_copy(deep=True) for row in state.known_skills],
        relationships={key: value.model_copy(deep=True) for key, value in state.relationships.items()},
        active_quests=[quest.model_copy(deep=True) for quest in state.active_quests],
        plot_threads=[thread.model_copy(deep=True) for thread in state.plot_threads],
    )


def _project(
    state: WorldStateView, change_set: ChangeSet, elapsed_minutes: int
) -> WorldStateView:
    projected = _copy_state(state)
    characters = {projected.player.id: projected.player}
    characters.update({c.id: c for c in projected.present_characters})

    for change in change_set.changes:
        character = characters.get(change.target_id)
        if change.kind is ChangeKind.CHARACTER_FIELD and character is not None:
            setattr(character, change.field, change.after)
        elif change.kind is ChangeKind.CHARACTER_LOCATION and character is not None:
            character.location_id = str(change.after)
            location = projected.graph.by_id(str(change.after))
            character.location_key = location.key if location else None
            if character.id == projected.player.id:
                projected.location = location
        elif change.kind is ChangeKind.CHARACTER_DEATH and character is not None:
            character.alive = False
            character.health = 0
        elif change.kind in (ChangeKind.INVENTORY_ADD, ChangeKind.INVENTORY_REMOVE):
            if change.target_id != projected.player.id:
                continue
            item_key = str(change.payload["item_key"])
            amount = int(change.payload.get("quantity", 1))
            inventory_row = next(
                (item for item in projected.inventory if item.item_key == item_key), None
            )
            delta = amount if change.kind is ChangeKind.INVENTORY_ADD else -amount
            if inventory_row is None and delta > 0:
                projected.inventory.append(
                    InventoryItem(
                        character_id=projected.player.id,
                        item_key=item_key,
                        quantity=delta,
                    )
                )
            elif inventory_row is not None:
                inventory_row.quantity += delta
                if inventory_row.quantity <= 0:
                    projected.inventory.remove(inventory_row)
        elif change.kind is ChangeKind.SKILL_LEARN and change.target_id == projected.player.id:
            skill_key = str(change.payload["skill_key"])
            if not projected.has_skill(skill_key):
                projected.known_skills.append(
                    CharacterSkill(character_id=projected.player.id, skill_key=skill_key)
                )
        elif change.kind is ChangeKind.SKILL_USED and change.target_id == projected.player.id:
            skill_row = projected.skill_row(str(change.payload["skill_key"]))
            if skill_row is not None:
                skill_row.last_used_minute = int(change.payload["at_minute"])
        elif change.kind is ChangeKind.QUEST_STATUS:
            quest = next((q for q in projected.active_quests if q.id == change.target_id), None)
            if quest is not None:
                quest.status = change.after

    target_minute = projected.world.current_minute + max(0, elapsed_minutes)
    projected.world.current_minute = target_minute
    projected.time = projected.clock.to_world_time(target_minute)
    return projected


def _merge(target: ChangeSet, source: ChangeSet) -> None:
    target.changes.extend(source.changes)
    target.events.extend(source.events)
    target.relationship_changes.extend(source.relationship_changes)
    target.memories.extend(source.memories)
    target.director_events.extend(source.director_events)

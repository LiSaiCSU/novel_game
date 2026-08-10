from __future__ import annotations

import pytest
from pydantic import ValidationError

from engine.actions.intent_parser import IntentParser
from engine.actions.planner import ActionPlanExecutor
from engine.actions.resolver import ActionResolver
from engine.actions.schema import (
    Action,
    ActionCondition,
    ActionOutcome,
    ActionPlan,
    ActionPlanIntent,
    ActionPrimitive,
    ActionPrimitiveIntent,
    PlayerIntent,
    PredicateKind,
    RuleResult,
)
from engine.core.mutations import ChangeSet, character_death
from engine.core.types import ActionType, ReasonCode
from engine.events.builder import EventBuilder
from engine.relationships.manager import RelationshipManager
from engine.rules.engine import RuleEngine


def _executor(pack, ctx) -> ActionPlanExecutor:
    return ActionPlanExecutor(
        RuleEngine(),
        ActionResolver(
            EventBuilder(pack, ctx.state.world.id, "action-plan-test"),
            RelationshipManager(pack),
        ),
    )


def test_later_primitive_validates_against_projected_inventory(pack, ctx) -> None:
    owned = {row.item_key for row in ctx.state.inventory}
    acquired = next(item for item in pack.items if item["key"] not in owned)
    recipient = ctx.state.present_characters[0]
    plan = ActionPlan(
        primitives=[
            ActionPrimitive(
                primitive_id="pick_up",
                action=Action(
                    action_type=ActionType.PICKUP,
                    actor_id=ctx.state.player.id,
                    item_key=acquired["key"],
                ),
            ),
            ActionPrimitive(
                primitive_id="give_it",
                action=Action(
                    action_type=ActionType.GIVE_ITEM,
                    actor_id=ctx.state.player.id,
                    target_id=recipient.id,
                    item_key=acquired["key"],
                ),
                condition=ActionCondition(
                    kind=PredicateKind.HAS_ITEM,
                    item_key=acquired["key"],
                ),
            ),
        ]
    )

    result = _executor(pack, ctx).execute(ctx, plan)

    assert result.rule_result.allowed
    assert [step["status"] for step in result.steps] == ["RESOLVED", "RESOLVED"]
    assert result.outcome.time_cost_minutes > 0
    assert len(result.change_set.events) == 2
    first, second = result.change_set.events
    assert first.payload["primitive_id"] == "pick_up"
    assert second.payload["primitive_id"] == "give_it"
    assert first.id in second.cause_event_ids


def test_rule_rejection_discards_all_prior_primitive_changes(pack, ctx) -> None:
    owned = next(row for row in ctx.state.inventory if row.quantity > 0)
    plan = ActionPlan(
        primitives=[
            ActionPrimitive(
                primitive_id="drop_item",
                action=Action(
                    action_type=ActionType.DROP,
                    actor_id=ctx.state.player.id,
                    item_key=owned.item_key,
                    quantity=owned.quantity,
                ),
            ),
            ActionPrimitive(
                primitive_id="use_missing_item",
                action=Action(
                    action_type=ActionType.USE_ITEM,
                    actor_id=ctx.state.player.id,
                    item_key=owned.item_key,
                ),
            ),
        ]
    )

    result = _executor(pack, ctx).execute(ctx, plan)

    assert not result.rule_result.allowed
    assert result.rule_result.reason_code is ReasonCode.ITEM_NOT_OWNED
    assert result.rule_result.details["discarded_primitives"] == ["drop_item"]
    assert [step["status"] for step in result.steps] == ["DISCARDED", "REJECTED"]
    assert result.change_set.changes == []
    assert [event.event_type for event in result.change_set.events] == ["REJECTED_ACTION"]


class _FailedAttemptPlugin:
    key = "failed-attempt"
    api_version = "1"
    handled_actions = frozenset({ActionType.CUSTOM})

    def validate_action(self, ctx, action):
        return RuleResult.ok()

    def resolve_action(self, ctx, action, rule_result, events):
        changes = ChangeSet()
        changes.add_event(
            events.build(
                "FAILED_ATTEMPT",
                actor_id=action.actor_id,
                world_minute=ctx.now,
            )
        )
        return (
            ActionOutcome(
                action_type=action.action_type,
                success=False,
                summary_key="FAILED_ATTEMPT",
                time_cost_minutes=5,
            ),
            changes,
        )


class _KillTargetPlugin:
    key = "kill-target"
    api_version = "1"
    handled_actions = frozenset({ActionType.CUSTOM})

    def validate_action(self, ctx, action):
        return RuleResult.ok()

    def resolve_action(self, ctx, action, rule_result, events):
        changes = ChangeSet()
        changes.add(character_death(action.target_id, "test plan death"))
        return (
            ActionOutcome(
                action_type=action.action_type,
                success=True,
                summary_key="TARGET_DIED",
                time_cost_minutes=1,
            ),
            changes,
        )


def test_resolved_failure_is_canonical_but_dependent_step_is_skipped(pack, ctx) -> None:
    original = pack.rule_plugin
    pack.rule_plugin = _FailedAttemptPlugin()
    plan = ActionPlan(
        primitives=[
            ActionPrimitive(
                primitive_id="attempt",
                action=Action(
                    action_type=ActionType.CUSTOM,
                    actor_id=ctx.state.player.id,
                ),
            ),
            ActionPrimitive(
                primitive_id="celebrate",
                action=Action(
                    action_type=ActionType.OBSERVE,
                    actor_id=ctx.state.player.id,
                ),
                condition=ActionCondition(
                    kind=PredicateKind.PREVIOUS_SUCCEEDED,
                    primitive_id="attempt",
                ),
            ),
        ]
    )
    try:
        result = _executor(pack, ctx).execute(ctx, plan)
    finally:
        pack.rule_plugin = original

    assert result.rule_result.allowed
    assert not result.outcome.success
    assert [step["status"] for step in result.steps] == [
        "RESOLVED",
        "SKIPPED_CONDITION",
    ]
    assert [event.event_type for event in result.change_set.events] == ["FAILED_ATTEMPT"]


def test_dead_target_is_not_present_for_later_primitive_condition(pack, ctx) -> None:
    target = ctx.state.present_characters[0]
    original = pack.rule_plugin
    pack.rule_plugin = _KillTargetPlugin()
    plan = ActionPlan(
        primitives=[
            ActionPrimitive(
                primitive_id="kill_target",
                action=Action(
                    action_type=ActionType.CUSTOM,
                    actor_id=ctx.state.player.id,
                    target_id=target.id,
                ),
            ),
            ActionPrimitive(
                primitive_id="address_target",
                action=Action(
                    action_type=ActionType.TALK,
                    actor_id=ctx.state.player.id,
                    target_id=target.id,
                ),
                condition=ActionCondition(
                    kind=PredicateKind.TARGET_PRESENT,
                    target_id=target.id,
                ),
            ),
        ]
    )
    try:
        result = _executor(pack, ctx).execute(ctx, plan)
    finally:
        pack.rule_plugin = original

    assert result.rule_result.allowed
    assert [step["status"] for step in result.steps] == [
        "RESOLVED",
        "SKIPPED_CONDITION",
    ]
    assert result.representative_action.action_type is ActionType.CUSTOM


def test_plan_over_time_limit_is_rejected_without_partial_changes(pack, ctx) -> None:
    plan = ActionPlan(
        primitives=[
            ActionPrimitive(
                primitive_id="wait_one",
                action=Action(
                    action_type=ActionType.WAIT,
                    actor_id=ctx.state.player.id,
                    duration_minutes=40,
                ),
            ),
            ActionPrimitive(
                primitive_id="wait_two",
                action=Action(
                    action_type=ActionType.WAIT,
                    actor_id=ctx.state.player.id,
                    duration_minutes=40,
                ),
            ),
        ]
    )

    result = ActionPlanExecutor(
        RuleEngine(),
        ActionResolver(
            EventBuilder(pack, ctx.state.world.id, "long-plan"),
            RelationshipManager(pack),
        ),
        max_total_minutes=60,
    ).execute(ctx, plan)

    assert not result.rule_result.allowed
    assert result.rule_result.reason_code is ReasonCode.TIME_LIMIT_EXCEEDED
    assert result.change_set.changes == []


def test_intent_compiler_binds_every_primitive(pack, context_builder, state) -> None:
    recipient = state.present_characters[0]
    item = next(row for row in state.inventory if row.quantity > 0)
    intent = PlayerIntent(
        action_type=ActionType.GIVE_ITEM,
        raw_text="我先把东西交给他，然后问候一声",
        plan=ActionPlanIntent(
            primitives=[
                ActionPrimitiveIntent(
                    primitive_id="give_item",
                    action_type=ActionType.GIVE_ITEM,
                    target_key=recipient.key,
                    item_key=item.item_key,
                ),
                ActionPrimitiveIntent(
                    primitive_id="greet",
                    action_type=ActionType.TALK,
                    target_key=recipient.key,
                    condition=ActionCondition(
                        kind=PredicateKind.PREVIOUS_SUCCEEDED,
                        primitive_id="give_item",
                    ),
                ),
            ]
        ),
    )

    _action, plan, notes = IntentParser(pack, context_builder).resolve(state, intent)

    assert notes == []
    assert [step.action.target_id for step in plan.primitives] == [
        recipient.id,
        recipient.id,
    ]
    assert plan.primitives[1].condition is not None
    assert plan.primitives[1].condition.primitive_id == "give_item"


def test_invalid_forward_condition_becomes_clarification(pack, context_builder, state) -> None:
    intent = PlayerIntent(
        action_type=ActionType.OBSERVE,
        raw_text="条件不明确的复合动作",
        plan=ActionPlanIntent(
            primitives=[
                ActionPrimitiveIntent(
                    primitive_id="first",
                    action_type=ActionType.OBSERVE,
                    condition=ActionCondition(
                        kind=PredicateKind.PREVIOUS_SUCCEEDED,
                        primitive_id="later",
                    ),
                ),
                ActionPrimitiveIntent(
                    primitive_id="later",
                    action_type=ActionType.WAIT,
                ),
            ]
        ),
    )

    action, plan, notes = IntentParser(pack, context_builder).resolve(state, intent)

    assert intent.ambiguity == "invalid_action_plan"
    assert action.action_type is ActionType.CUSTOM
    assert len(plan.primitives) == 1
    assert "condition_requires_earlier_primitive:later" in notes


def test_legacy_secondary_actions_are_rejected_instead_of_ignored() -> None:
    with pytest.raises(ValidationError):
        PlayerIntent.model_validate(
            {
                "action_type": "OBSERVE",
                "secondary_actions": [{"type": "REST"}],
            }
        )

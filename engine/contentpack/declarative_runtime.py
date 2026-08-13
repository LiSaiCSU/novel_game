"""Translate validated creator rules into canonical engine mutations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from engine.actions.schema import Action, ActionOutcome
from engine.contentpack.declarative import DeclarativeRule, RuleEffect, evaluate
from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.ids import PLAYER_KEY, deterministic_id
from engine.core.models import Relationship
from engine.core.mutations import ChangeSet
from engine.relationships.manager import RelationshipManager, band_for_importance
from engine.world.state_view import WorldStateView


def _entity_id(state: WorldStateView, kind: str, key: str) -> str:
    return deterministic_id(f"{state.world.id}/{kind}", key)


def _value(raw: Any, context: dict[str, Any]) -> Any:
    return evaluate(raw, context) if isinstance(raw, dict) and "op" in raw else raw


def _context(state: WorldStateView, action: Action, outcome: ActionOutcome) -> dict[str, Any]:
    return {
        "action": action.model_dump(mode="json"),
        "outcome": outcome.model_dump(mode="json"),
        "player": {
            "key": PLAYER_KEY,
            "location": state.location_key(),
            "attributes": deepcopy(state.player.attributes),
            "resources": deepcopy(state.player.resources),
            "progressions": deepcopy(state.player.progressions),
            "properties": deepcopy(state.player.properties),
        },
        "world": {"minute": state.world.current_minute, "tension": state.world.narrative_tension},
    }


def apply_declarative_rules(
    pack: ContentPack,
    state: WorldStateView,
    action: Action,
    outcome: ActionOutcome,
    change_set: ChangeSet,
) -> list[str]:
    """Apply bounded rules after adjudication and before the consistency guard."""
    context = _context(state, action, outcome)
    applied: list[str] = []
    projected = {
        "attributes": deepcopy(state.player.attributes),
        "resources": deepcopy(state.player.resources),
        "progressions": deepcopy(state.player.progressions),
        "properties": deepcopy(state.player.properties),
    }
    for raw in pack.declarative_rules:
        rule = DeclarativeRule.model_validate(raw)
        if not bool(_value(rule.condition, context)):
            continue
        for effect in rule.effects:
            _apply_effect(pack, state, outcome, change_set, projected, context, rule, effect)
        applied.append(rule.key)
    return applied


def _apply_effect(
    pack: ContentPack,
    state: WorldStateView,
    outcome: ActionOutcome,
    change_set: ChangeSet,
    projected: dict[str, dict[str, Any]],
    context: dict[str, Any],
    rule: DeclarativeRule,
    effect: RuleEffect,
) -> None:
    reason = f"declarative:{rule.key}"
    if effect.op == "set_player_data":
        namespace, key = effect.field.split(".", 1)
        before = deepcopy(projected[namespace])
        projected[namespace][key] = _value(effect.value, context)
        change_set.add(mut.character_field(
            state.player.id, namespace, before, deepcopy(projected[namespace]), reason
        ))
        context["player"][namespace] = deepcopy(projected[namespace])
        return
    if effect.op == "adjust_player_resource":
        before = deepcopy(projected["resources"])
        entry = projected["resources"].get(effect.field, 0)
        current = float(entry.get("current", 0)) if isinstance(entry, dict) else float(entry)
        delta = float(_value(effect.value, context))
        definition: dict[str, Any] = next(
            (item for item in pack.meta.get("resource_definitions", []) if item.get("key") == effect.field),
            {},
        )
        minimum = float(definition.get("minimum", 0))
        maximum = float(definition.get("maximum", max(current + delta, 100)))
        value = max(minimum, min(maximum, current + delta))
        projected["resources"][effect.field] = {"current": value, "maximum": maximum}
        change_set.add(mut.character_field(
            state.player.id, "resources", before, deepcopy(projected["resources"]), reason
        ))
        context["player"]["resources"] = deepcopy(projected["resources"])
        return
    if effect.op == "relationship_delta":
        target_id = _entity_id(state, "character", effect.target)
        manager = RelationshipManager(pack)
        proposed = {key: _value(value, context) for key, value in effect.values.items()}
        deltas, flags = manager.clamp_deltas(proposed, band_for_importance(outcome.importance))
        if not deltas:
            return
        relationship = state.relationship_with(target_id) or Relationship(
            world_id=state.world.id,
            character_a_id=state.player.id,
            character_b_id=target_id,
        )
        _, audit = manager.apply(
            relationship,
            deltas,
            reason=reason,
            world_minute=state.world.current_minute,
            event_id=change_set.events[-1].id if change_set.events else None,
            clamped_flags=flags,
        )
        actual = {item.dimension: item.delta for item in audit}
        if actual:
            change_set.add(manager.to_state_change(state.player.id, target_id, actual, reason))
            change_set.relationship_changes.extend(audit)
        return
    if effect.op in {"inventory_add", "inventory_remove"}:
        quantity = max(1, min(99, int(_value(effect.quantity, context))))
        constructor = mut.inventory_add if effect.op == "inventory_add" else mut.inventory_remove
        change_set.add(constructor(state.player.id, effect.target, quantity, reason))
        return
    if effect.op == "quest_status":
        quest = next((item for item in state.active_quests if item.key == effect.target), None)
        status_before = str(quest.status) if quest else "offered"
        change_set.add(mut.quest_status(
            _entity_id(state, "quest", effect.target), status_before,
            str(_value(effect.value, context)), reason
        ))
        return
    if effect.op == "plot_thread_update":
        payload = {key: _value(value, context) for key, value in effect.values.items()}
        change_set.add(mut.plot_thread_update(
            _entity_id(state, "thread", effect.target), payload, reason
        ))
        return
    if effect.op == "location_flag":
        payload = {key: _value(value, context) for key, value in effect.values.items()}
        change_set.add(mut.location_flag(
            _entity_id(state, "location", effect.target), payload, reason
        ))

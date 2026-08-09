"""ActionResolver - turns a permitted action into facts.

This is where dice are rolled and numbers move. Everything it produces is a
:class:`ChangeSet` proposal for the transaction layer; nothing is written here.
The narrative model later *describes* these facts and may not alter them.
"""

from __future__ import annotations

from typing import Any

from engine.actions.schema import Action, ActionOutcome, RuleResult
from engine.core import mutations as mut
from engine.core.models import Character
from engine.core.mutations import ChangeSet
from engine.core.types import ActionType, ReasonCode, Visibility
from engine.events.builder import EventBuilder, witnesses_for
from engine.relationships.manager import RelationshipManager
from engine.rules.base import RuleContext, clamp, time_cost
from engine.rules.combat import CombatRules, DetectionRules
from engine.rules.cultivation import CultivationRules
from engine.rules.economy import EconomyRules
from engine.rules.movement import MovementRules


class ActionResolver:
    def __init__(self, events: EventBuilder, relationships: RelationshipManager) -> None:
        self.events = events
        self.relationships = relationships

    # ------------------------------------------------------------------
    def resolve(
        self, ctx: RuleContext, action: Action, rule_result: RuleResult
    ) -> tuple[ActionOutcome, ChangeSet]:
        changes = ChangeSet()
        if not rule_result.allowed:
            return self._rejected(ctx, action, rule_result, changes), changes

        handler = getattr(self, f"_do_{action.action_type.lower()}", None)
        if handler is None:
            return self._do_custom(ctx, action, changes)
        return handler(ctx, action, changes)

    # ------------------------------------------------------------------
    def _rejected(
        self, ctx: RuleContext, action: Action, rule_result: RuleResult, changes: ChangeSet
    ) -> ActionOutcome:
        changes.add_event(
            self.events.build(
                "REJECTED_ACTION",
                actor_id=action.actor_id,
                location_id=ctx.state.player.location_id,
                payload={
                    "action_type": str(action.action_type),
                    "reason_code": str(rule_result.reason_code),
                    "reason": rule_result.reason,
                    "details": rule_result.details,
                },
                world_minute=ctx.now,
                visibility=Visibility.PRIVATE,
            )
        )
        return ActionOutcome(
            action_type=action.action_type,
            success=False,
            summary_key="rejected",
            time_cost_minutes=0,
            facts={
                "reason_code": str(rule_result.reason_code),
                "reason": rule_result.reason,
                **rule_result.details,
            },
            importance=0.02,
        )

    def _actor(self, ctx: RuleContext, action: Action) -> Character:
        return ctx.state.character_by_id(action.actor_id) or ctx.state.player

    def _finish(
        self,
        ctx: RuleContext,
        action: Action,
        changes: ChangeSet,
        *,
        success: bool,
        summary_key: str,
        minutes: int,
        facts: dict[str, Any],
        importance: float,
        event_type: str | None = None,
        event_payload: dict[str, Any] | None = None,
        target_ids: list[str] | None = None,
    ) -> tuple[ActionOutcome, ChangeSet]:
        if event_type:
            visibility = Visibility(ctx.pack.event_visibility(event_type))
            changes.add_event(
                self.events.build(
                    event_type,
                    actor_id=action.actor_id,
                    target_ids=target_ids or ([action.target_id] if action.target_id else []),
                    location_id=ctx.state.player.location_id,
                    payload=event_payload or facts,
                    world_minute=ctx.now,
                    rng_seed=ctx.rng.seed_hex,
                    importance=importance,
                    visibility=visibility,
                    witnesses=witnesses_for(
                        visibility, ctx.state.present_characters, action.actor_id
                    ),
                )
            )
        return (
            ActionOutcome(
                action_type=action.action_type,
                success=success,
                summary_key=summary_key,
                time_cost_minutes=minutes,
                facts=facts,
                importance=importance,
            ),
            changes,
        )

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------
    def _do_move(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        result = MovementRules.validate_action(ctx, action)
        minutes = MovementRules.resolve_cost(
            ctx, int(result.details.get("minutes", 0)), int(result.details.get("hops", 1))
        )
        destination = ctx.state.graph.by_id(action.target_location_id)
        origin = ctx.state.graph.by_id(actor.location_id)
        if destination is None:
            return self._finish(
                ctx,
                action,
                changes,
                success=False,
                summary_key="rejected",
                minutes=0,
                facts={"reason_code": str(ReasonCode.LOCATION_NOT_FOUND)},
                importance=0.02,
            )
        if origin is not None and origin.id == destination.id:
            return self._finish(
                ctx,
                action,
                changes,
                success=True,
                summary_key="MOVE_SAME",
                minutes=int(ctx.rule("time_costs.MOVE_LOCAL.min", 10)),
                facts={"to_location": destination.name, "to_location_key": destination.key},
                importance=0.02,
            )

        changes.add(
            mut.character_move(actor.id, actor.location_id, destination.id, reason="travel")
        )
        return self._finish(
            ctx,
            action,
            changes,
            success=True,
            summary_key="MOVE",
            minutes=minutes,
            facts={
                "from_location": origin.name if origin else "",
                "from_location_key": origin.key if origin else "",
                "to_location": destination.name,
                "to_location_key": destination.key,
                "path": result.details.get("path", []),
                "minutes": minutes,
            },
            importance=ctx.pack.event_importance("MOVE"),
            event_type="MOVE",
        )

    # ------------------------------------------------------------------
    # Perception
    # ------------------------------------------------------------------
    def _do_observe(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        state = ctx.state
        location = state.location
        minutes = time_cost(ctx, str(ActionType.OBSERVE))
        facts = {
            "location": location.name if location else "",
            "location_key": location.key if location else "",
            "description": location.description if location else "",
            "present": [
                {"key": c.key, "name": c.display_name, "activity": c.current_emotion.dominant}
                for c in state.present_characters
            ],
            "danger_level": location.danger_level if location else 0,
        }
        return self._finish(
            ctx,
            action,
            changes,
            success=True,
            summary_key="OBSERVE",
            minutes=minutes,
            facts=facts,
            importance=0.05,
            event_type="OBSERVATION",
        )

    def _do_search(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        state = ctx.state
        actor = self._actor(ctx, action)
        minutes = time_cost(ctx, str(ActionType.SEARCH))
        location = state.location
        base = 0.15 + actor.perception * 0.015 + (location.danger_level if location else 0) * 0.02
        found = ctx.rng.chance(clamp(base, 0.05, 0.75))
        facts: dict[str, Any] = {
            "location": location.name if location else "",
            "found": found,
        }
        if found:
            # Only things the pack says exist may be found; nothing is invented.
            candidates = [
                item["key"]
                for item in ctx.pack.items
                if item.get("type") in ("herb", "material", "misc")
                and item.get("rarity") in ("common", "uncommon")
            ]
            if candidates:
                item_key = ctx.rng.choice(candidates)
                quantity = ctx.rng.randint(1, 2)
                changes.add(mut.inventory_add(actor.id, item_key, quantity, reason="search"))
                raw = ctx.pack.item(item_key) or {}
                facts["item_key"] = item_key
                facts["item_name"] = raw.get("name", item_key)
                facts["quantity"] = quantity
            else:
                facts["found"] = False
        return self._finish(
            ctx,
            action,
            changes,
            success=True,
            summary_key="SEARCH" if facts["found"] else "SEARCH_EMPTY",
            minutes=minutes,
            facts=facts,
            importance=0.15 if facts["found"] else 0.05,
            event_type="ITEM_ACQUIRED" if facts["found"] else "OBSERVATION",
        )

    def _do_hide(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        minutes = time_cost(ctx, str(ActionType.HIDE))
        detected, chance = DetectionRules.roll_detected(ctx, actor, ctx.state.present_characters)
        return self._finish(
            ctx,
            action,
            changes,
            success=not detected,
            summary_key="HIDE_FAILED" if detected else "HIDE_SUCCESS",
            minutes=minutes,
            facts={"detected": detected, "detection_chance": round(chance, 3)},
            importance=0.08,
        )

    def _do_follow(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        target = ctx.state.character_by_id(action.target_id)
        actor = self._actor(ctx, action)
        minutes = time_cost(ctx, str(ActionType.FOLLOW))
        detected, chance = DetectionRules.roll_detected(
            ctx, actor, [target] if target else []
        )
        return self._finish(
            ctx,
            action,
            changes,
            success=True,
            summary_key="FOLLOW",
            minutes=minutes,
            facts={
                "target": target.display_name if target else "",
                "target_key": target.key if target else "",
                "detected": detected,
                "detection_chance": round(chance, 3),
            },
            importance=0.1,
        )

    # ------------------------------------------------------------------
    # Social
    # ------------------------------------------------------------------
    def _do_talk(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        return self._social(ctx, action, changes, summary_key="TALK")

    def _do_ask(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        return self._social(ctx, action, changes, summary_key="ASK")

    def _do_conversation(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        return self._social(ctx, action, changes, summary_key="CONVERSATION")

    def _social(
        self, ctx: RuleContext, action: Action, changes: ChangeSet, *, summary_key: str
    ) -> tuple[ActionOutcome, ChangeSet]:
        """The resolver only establishes that contact happened and how costly it was.

        Whether the target complies is the NPC agent's decision, validated
        downstream - not a dice roll here.
        """
        target = ctx.state.character_by_id(action.target_id)
        minutes = time_cost(ctx, str(action.action_type))
        facts: dict[str, Any] = {
            "target": target.display_name if target else "",
            "target_key": target.key if target else "",
            "target_id": target.id if target else None,
            "method": action.method,
            "style": action.style,
            "topic": action.goal.topic,
            "request_size": str(action.request_size),
            "utterance": action.utterance,
        }
        if target is not None:
            deltas = self.relationships.interaction_deltas()
            if deltas:
                changes.add(
                    self.relationships.to_state_change(
                        target.id, ctx.state.player.id, deltas, reason="interaction"
                    )
                )
        return self._finish(
            ctx,
            action,
            changes,
            success=True,
            summary_key=summary_key,
            minutes=minutes,
            facts=facts,
            importance=ctx.pack.event_importance("CONVERSATION"),
            event_type="CONVERSATION",
        )

    # ------------------------------------------------------------------
    # Cultivation
    # ------------------------------------------------------------------
    def _do_cultivate(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        minutes = action.duration_minutes or int(ctx.rule("time_costs.CULTIVATE.default", 240))
        gain = CultivationRules.calculate_gain(ctx, actor, minutes)
        if gain.xp_ratio > 0:
            changes.add(
                mut.character_field(
                    actor.id,
                    "cultivation_progress",
                    round(gain.progress_before, 6),
                    round(gain.progress_after, 6),
                    reason="cultivation",
                )
            )
        regen = float(ctx.rule("combat.spiritual_power_regen_per_hour", 0.08)) * (minutes / 60.0)
        new_sp = min(actor.max_spiritual_power, int(actor.spiritual_power + actor.max_spiritual_power * regen))
        if new_sp != actor.spiritual_power:
            changes.add(
                mut.character_field(
                    actor.id, "spiritual_power", actor.spiritual_power, new_sp, reason="cultivation"
                )
            )
        return self._finish(
            ctx,
            action,
            changes,
            success=True,
            summary_key="CULTIVATE",
            minutes=minutes,
            facts={
                "minutes": minutes,
                "progress_before": round(gain.progress_before, 4),
                "progress_after": round(gain.progress_after, 4),
                "gain": round(gain.xp_ratio, 4),
                "diminished": gain.diminished,
                "breakdown": gain.breakdown,
                "ready_for_breakthrough": gain.progress_after >= 0.999,
            },
            importance=ctx.pack.event_importance("CULTIVATION_SESSION"),
            event_type="CULTIVATION_SESSION",
        )

    def _do_breakthrough(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        ladder = ctx.pack.realms
        minutes = action.duration_minutes or int(ctx.rule("time_costs.BREAKTHROUGH.default", 1440))

        pill_bonus = float(action.parameters.get("pill_bonus", 0.0))
        odds = CultivationRules.calculate_breakthrough(ctx, actor, pill_bonus=pill_bonus)
        succeeded = ctx.rng.chance(odds.chance)

        before = {
            "realm": actor.realm,
            "realm_stage": actor.realm_stage,
            "display": ladder.display(actor.realm, actor.realm_stage),
        }

        if succeeded:
            new_max_hp = ladder.max_health(odds.to_realm, odds.to_stage)
            new_max_sp = ladder.max_spiritual_power(odds.to_realm, odds.to_stage)
            changes.extend(
                [
                    mut.character_field(actor.id, "realm", actor.realm, odds.to_realm, reason="breakthrough"),
                    mut.character_field(
                        actor.id, "realm_stage", actor.realm_stage, odds.to_stage, reason="breakthrough"
                    ),
                    mut.character_field(
                        actor.id, "cultivation_progress", actor.cultivation_progress, 0.0, reason="breakthrough"
                    ),
                    mut.character_field(actor.id, "max_health", actor.max_health, new_max_hp, reason="breakthrough"),
                    mut.character_field(actor.id, "health", actor.health, new_max_hp, reason="breakthrough"),
                    mut.character_field(
                        actor.id, "max_spiritual_power", actor.max_spiritual_power, new_max_sp, reason="breakthrough"
                    ),
                    mut.character_field(
                        actor.id, "spiritual_power", actor.spiritual_power, new_max_sp, reason="breakthrough"
                    ),
                    mut.character_field(actor.id, "bottleneck", actor.bottleneck, 0.0, reason="breakthrough"),
                    mut.character_field(
                        actor.id,
                        "mental_state",
                        actor.mental_state,
                        round(clamp(actor.mental_state + float(ctx.rule("breakthrough.success.mental_state_gain", 0.1)), 0.0, 1.0), 4),
                        reason="breakthrough",
                    ),
                ]
            )
            after = {
                "realm": odds.to_realm,
                "realm_stage": odds.to_stage,
                "display": ladder.display(odds.to_realm, odds.to_stage),
            }
            facts = {
                "success": True,
                "chance": round(odds.chance, 4),
                "breakdown": odds.breakdown,
                "realm_before": before["display"],
                "realm_after": after["display"],
            }
            changes.add_event(
                self.events.build(
                    "BREAKTHROUGH",
                    actor_id=actor.id,
                    location_id=actor.location_id,
                    before=before,
                    after=after,
                    causes=[f"cultivation:{minutes}m"] + ([f"pill_bonus:{pill_bonus}"] if pill_bonus else []),
                    payload=facts,
                    world_minute=ctx.now,
                    rng_seed=ctx.rng.seed_hex,
                    importance=ctx.pack.event_importance("BREAKTHROUGH"),
                    witnesses=witnesses_for(
                        Visibility(ctx.pack.event_visibility("BREAKTHROUGH")),
                        ctx.state.present_characters,
                        actor.id,
                    ),
                )
            )
            return ActionOutcome(
                action_type=action.action_type,
                success=True,
                summary_key="BREAKTHROUGH_SUCCESS",
                time_cost_minutes=minutes,
                facts=facts,
                importance=ctx.pack.event_importance("BREAKTHROUGH"),
            ), changes

        penalties = CultivationRules.failure_penalties(ctx, actor)
        health_loss = int(actor.max_health * penalties["health_loss_ratio"])
        new_health = max(1, actor.health - health_loss)
        new_injuries = round(clamp(actor.injuries + penalties["injury_gain"], 0.0, 1.0), 4)
        new_mental = round(clamp(actor.mental_state - penalties["mental_state_loss"], 0.0, 1.0), 4)
        bottleneck_cap = float((ladder.bottleneck or {}).get("max", 0.6))
        new_bottleneck = round(clamp(actor.bottleneck + penalties["bottleneck_gain"], 0.0, bottleneck_cap), 4)

        changes.extend(
            [
                mut.character_field(actor.id, "health", actor.health, new_health, reason="breakthrough_failed"),
                mut.character_field(actor.id, "injuries", actor.injuries, new_injuries, reason="breakthrough_failed"),
                mut.character_field(actor.id, "mental_state", actor.mental_state, new_mental, reason="breakthrough_failed"),
                mut.character_field(actor.id, "bottleneck", actor.bottleneck, new_bottleneck, reason="breakthrough_failed"),
            ]
        )
        died = ctx.rng.chance(penalties["death_chance"]) if penalties["death_chance"] > 0 else False
        if died:
            changes.add(mut.character_death(actor.id, reason="cultivation_backlash"))

        facts = {
            "success": False,
            "chance": round(odds.chance, 4),
            "breakdown": odds.breakdown,
            "health_loss": health_loss,
            "injuries": new_injuries,
            "died": died,
        }
        changes.add_event(
            self.events.build(
                "BREAKTHROUGH_FAILED",
                actor_id=actor.id,
                location_id=actor.location_id,
                before=before,
                after=before,
                payload=facts,
                world_minute=ctx.now,
                rng_seed=ctx.rng.seed_hex,
                importance=ctx.pack.event_importance("BREAKTHROUGH_FAILED"),
            )
        )
        return ActionOutcome(
            action_type=action.action_type,
            success=False,
            summary_key="BREAKTHROUGH_FAILED",
            time_cost_minutes=minutes,
            facts=facts,
            importance=ctx.pack.event_importance("BREAKTHROUGH_FAILED"),
        ), changes

    # ------------------------------------------------------------------
    # Combat
    # ------------------------------------------------------------------
    def _do_attack(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        target = ctx.state.character_by_id(action.target_id)
        minutes = time_cost(ctx, str(ActionType.ATTACK))
        if target is None:
            return self._finish(
                ctx, action, changes, success=False, summary_key="rejected", minutes=0,
                facts={"reason_code": str(ReasonCode.TARGET_NOT_FOUND)}, importance=0.02,
            )

        mastery = 0.0
        if action.skill_key:
            row = ctx.state.skill_row(action.skill_key)
            mastery = row.mastery if row else 0.0
            raw = ctx.pack.skill(action.skill_key) or {}
            cost = int(raw.get("spiritual_cost", 0))
            if cost:
                changes.add(
                    mut.character_field(
                        actor.id, "spiritual_power", actor.spiritual_power,
                        max(0, actor.spiritual_power - cost), reason="skill_cost",
                    )
                )
                changes.add(mut.skill_used(actor.id, action.skill_key, ctx.now))

        resolution = CombatRules.calculate_damage(
            ctx, actor, target, skill_key=action.skill_key, skill_mastery=mastery
        )
        facts: dict[str, Any] = {
            "target": target.display_name,
            "target_key": target.key,
            "hit": resolution.hit,
            "damage": resolution.damage,
            "hit_chance": round(resolution.hit_chance, 3),
            "hard_blocked": resolution.hard_blocked,
            "breakdown": resolution.breakdown,
            "skill_key": action.skill_key,
        }
        summary = "ATTACK_MISS"
        event_type = "COMBAT_DEFEAT"
        if resolution.hit:
            new_health = max(0, target.health - resolution.damage)
            changes.add(
                mut.character_field(
                    target.id, "health", target.health, new_health, reason="combat_damage"
                )
            )
            summary = "ATTACK_BLOCKED" if resolution.hard_blocked else "ATTACK_HIT"
            if new_health <= 0:
                changes.add(mut.character_death(target.id, reason="killed_in_combat"))
                facts["killed"] = True
                event_type = "DEATH"
            else:
                event_type = "COMBAT_VICTORY"
        importance = ctx.pack.event_importance(event_type)
        return self._finish(
            ctx, action, changes, success=resolution.hit, summary_key=summary, minutes=minutes,
            facts=facts, importance=importance, event_type=event_type, target_ids=[target.id],
        )

    def _do_defend(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        return self._finish(
            ctx, action, changes, success=True, summary_key="DEFEND",
            minutes=time_cost(ctx, str(ActionType.DEFEND)), facts={"defending": True}, importance=0.05,
        )

    def _do_use_skill(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        if action.target_id:
            return self._do_attack(ctx, action, changes)
        actor = self._actor(ctx, action)
        raw = ctx.pack.skill(action.skill_key or "") or {}
        cost = int(raw.get("spiritual_cost", 0))
        if cost:
            changes.add(
                mut.character_field(
                    actor.id, "spiritual_power", actor.spiritual_power,
                    max(0, actor.spiritual_power - cost), reason="skill_cost",
                )
            )
        changes.add(mut.skill_used(actor.id, action.skill_key or "", ctx.now))
        return self._finish(
            ctx, action, changes, success=True, summary_key="USE_SKILL",
            minutes=time_cost(ctx, str(ActionType.USE_SKILL)),
            facts={"skill": raw.get("name", action.skill_key), "skill_key": action.skill_key,
                   "effects": raw.get("effects", {})},
            importance=0.1,
        )

    # ------------------------------------------------------------------
    # Items and trade
    # ------------------------------------------------------------------
    def _do_use_item(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        item_key = action.item_key or ""
        raw = ctx.pack.item(item_key) or {}
        effects: dict[str, Any] = raw.get("effects", {}) or {}
        applied: dict[str, Any] = {}

        if "restore_health_ratio" in effects:
            healed = int(actor.max_health * float(effects["restore_health_ratio"]))
            new_health = min(actor.max_health, actor.health + healed)
            changes.add(mut.character_field(actor.id, "health", actor.health, new_health, reason="item"))
            applied["health"] = [actor.health, new_health]
        if "restore_spiritual_power_ratio" in effects:
            restored = int(actor.max_spiritual_power * float(effects["restore_spiritual_power_ratio"]))
            new_sp = min(actor.max_spiritual_power, actor.spiritual_power + restored)
            changes.add(
                mut.character_field(actor.id, "spiritual_power", actor.spiritual_power, new_sp, reason="item")
            )
            applied["spiritual_power"] = [actor.spiritual_power, new_sp]
        if "reduce_injury" in effects:
            new_injuries = round(clamp(actor.injuries - float(effects["reduce_injury"]), 0.0, 1.0), 4)
            changes.add(mut.character_field(actor.id, "injuries", actor.injuries, new_injuries, reason="item"))
            applied["injuries"] = [actor.injuries, new_injuries]
        if "teaches_skill" in effects:
            skill_key = str(effects["teaches_skill"])
            if not ctx.state.has_skill(skill_key):
                changes.add(mut.skill_learn(actor.id, skill_key, reason="item"))
                applied["learned_skill"] = skill_key

        consumable = raw.get("type") in ("pill", "talisman", "herb")
        if consumable:
            changes.add(mut.inventory_remove(actor.id, item_key, 1, reason="consumed"))

        return self._finish(
            ctx, action, changes, success=True, summary_key="USE_ITEM",
            minutes=time_cost(ctx, str(ActionType.USE_ITEM)),
            facts={"item": raw.get("name", item_key), "item_key": item_key, "applied": applied,
                   "breakthrough_bonus": effects.get("breakthrough_bonus")},
            importance=0.12,
        )

    def _do_give_item(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        target = ctx.state.character_by_id(action.target_id)
        item_key = action.item_key or ""
        raw = ctx.pack.item(item_key) or {}
        changes.add(mut.inventory_remove(actor.id, item_key, action.quantity, reason="gift"))
        if target is not None:
            changes.add(mut.inventory_add(target.id, item_key, action.quantity, reason="gift"))
        return self._finish(
            ctx, action, changes, success=True, summary_key="GIVE_ITEM",
            minutes=time_cost(ctx, str(ActionType.GIVE_ITEM)),
            facts={"item": raw.get("name", item_key), "item_key": item_key,
                   "quantity": action.quantity, "target": target.display_name if target else ""},
            importance=0.2, event_type="TRADE",
        )

    def _do_pickup(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        item_key = action.item_key or ""
        raw = ctx.pack.item(item_key) or {}
        changes.add(mut.inventory_add(actor.id, item_key, action.quantity, reason="pickup"))
        return self._finish(
            ctx, action, changes, success=True, summary_key="PICKUP",
            minutes=time_cost(ctx, str(ActionType.PICKUP)),
            facts={"item": raw.get("name", item_key), "item_key": item_key},
            importance=0.1, event_type="ITEM_ACQUIRED",
        )

    def _do_drop(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        item_key = action.item_key or ""
        raw = ctx.pack.item(item_key) or {}
        changes.add(mut.inventory_remove(actor.id, item_key, action.quantity, reason="drop"))
        return self._finish(
            ctx, action, changes, success=True, summary_key="DROP",
            minutes=time_cost(ctx, str(ActionType.DROP)),
            facts={"item": raw.get("name", item_key), "item_key": item_key}, importance=0.03,
        )

    def _do_buy(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        item_key = action.item_key or ""
        raw = ctx.pack.item(item_key) or {}
        price = EconomyRules.calculate_price(
            ctx, item_key, buying=True, reputation=actor.reputation.global_
        )
        total = price * action.quantity
        currency = EconomyRules.currency_key(ctx)
        changes.add(mut.inventory_remove(actor.id, currency, total, reason="purchase"))
        changes.add(mut.inventory_add(actor.id, item_key, action.quantity, reason="purchase"))
        return self._finish(
            ctx, action, changes, success=True, summary_key="BUY",
            minutes=time_cost(ctx, str(ActionType.BUY)),
            facts={"item": raw.get("name", item_key), "item_key": item_key,
                   "quantity": action.quantity, "cost": total},
            importance=0.1, event_type="TRADE",
        )

    def _do_sell(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        item_key = action.item_key or ""
        raw = ctx.pack.item(item_key) or {}
        price = EconomyRules.calculate_price(ctx, item_key, buying=False)
        total = price * action.quantity
        currency = EconomyRules.currency_key(ctx)
        changes.add(mut.inventory_remove(actor.id, item_key, action.quantity, reason="sale"))
        changes.add(mut.inventory_add(actor.id, currency, total, reason="sale"))
        return self._finish(
            ctx, action, changes, success=True, summary_key="SELL",
            minutes=time_cost(ctx, str(ActionType.SELL)),
            facts={"item": raw.get("name", item_key), "item_key": item_key,
                   "quantity": action.quantity, "cost": total},
            importance=0.1, event_type="TRADE",
        )

    def _do_steal(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        target = ctx.state.character_by_id(action.target_id)
        item_key = action.item_key or EconomyRules.currency_key(ctx)
        raw = ctx.pack.item(item_key) or {}
        observers = [c for c in ctx.state.present_characters if c.id != (target.id if target else "")]
        if target is not None:
            observers = [*observers, target]
        detected, chance = DetectionRules.roll_detected(ctx, actor, observers)
        succeeded = not detected
        facts: dict[str, Any] = {
            "target": target.display_name if target else "",
            "item": raw.get("name", item_key),
            "item_key": item_key,
            "detected": detected,
            "detection_chance": round(chance, 3),
        }
        if succeeded and target is not None:
            changes.add(mut.inventory_remove(target.id, item_key, action.quantity, reason="stolen"))
            changes.add(mut.inventory_add(actor.id, item_key, action.quantity, reason="theft"))
        return self._finish(
            ctx, action, changes, success=succeeded,
            summary_key="STEAL_SUCCESS" if succeeded else "STEAL_FAILED",
            minutes=time_cost(ctx, str(ActionType.STEAL)), facts=facts,
            importance=ctx.pack.event_importance("THEFT"), event_type="THEFT",
        )

    # ------------------------------------------------------------------
    # Rest / wait / quests / custom
    # ------------------------------------------------------------------
    def _do_rest(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        actor = self._actor(ctx, action)
        minutes = action.duration_minutes or time_cost(ctx, str(ActionType.REST))
        hours = minutes / 60.0
        hp_regen = int(actor.max_health * float(ctx.rule("combat.health_regen_per_hour", 0.03)) * hours)
        sp_regen = int(
            actor.max_spiritual_power * float(ctx.rule("combat.spiritual_power_regen_per_hour", 0.08)) * hours
        )
        new_health = min(actor.max_health, actor.health + hp_regen)
        new_sp = min(actor.max_spiritual_power, actor.spiritual_power + sp_regen)
        if new_health != actor.health:
            changes.add(mut.character_field(actor.id, "health", actor.health, new_health, reason="rest"))
        if new_sp != actor.spiritual_power:
            changes.add(
                mut.character_field(actor.id, "spiritual_power", actor.spiritual_power, new_sp, reason="rest")
            )
        return self._finish(
            ctx, action, changes, success=True, summary_key="REST", minutes=minutes,
            facts={"minutes": minutes, "health": [actor.health, new_health],
                   "spiritual_power": [actor.spiritual_power, new_sp]},
            importance=0.03,
        )

    def _do_wait(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        minutes = action.duration_minutes or time_cost(ctx, str(ActionType.WAIT))
        return self._finish(
            ctx, action, changes, success=True, summary_key="WAIT", minutes=minutes,
            facts={"minutes": minutes}, importance=0.02,
        )

    def _do_accept_quest(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        quest = next((q for q in ctx.state.active_quests if q.id == action.quest_id), None)
        if quest is not None:
            changes.add(mut.quest_status(quest.id, str(quest.status), "active", reason="accepted"))
        return self._finish(
            ctx, action, changes, success=True, summary_key="ACCEPT_QUEST",
            minutes=time_cost(ctx, str(ActionType.ACCEPT_QUEST)),
            facts={"quest": quest.name if quest else "", "quest_key": quest.key if quest else ""},
            importance=ctx.pack.event_importance("QUEST_ACCEPTED"), event_type="QUEST_ACCEPTED",
        )

    def _do_reject_quest(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        quest = next((q for q in ctx.state.active_quests if q.id == action.quest_id), None)
        if quest is not None:
            changes.add(mut.quest_status(quest.id, str(quest.status), "rejected", reason="declined"))
        return self._finish(
            ctx, action, changes, success=True, summary_key="REJECT_QUEST",
            minutes=time_cost(ctx, str(ActionType.REJECT_QUEST)),
            facts={"quest": quest.name if quest else "", "quest_key": quest.key if quest else ""},
            importance=0.05,
        )

    def _do_custom(
        self, ctx: RuleContext, action: Action, changes: ChangeSet
    ) -> tuple[ActionOutcome, ChangeSet]:
        return self._finish(
            ctx, action, changes, success=True, summary_key="CUSTOM",
            minutes=time_cost(ctx, str(ActionType.CUSTOM)),
            facts={"raw_text": action.raw_text}, importance=0.05,
        )

    # Query actions never move the world.
    def _do_query_status(self, ctx, action, changes):
        return self._query(ctx, action, changes, "status")

    def _do_query_inventory(self, ctx, action, changes):
        return self._query(ctx, action, changes, "inventory")

    def _do_query_relationships(self, ctx, action, changes):
        return self._query(ctx, action, changes, "relationships")

    def _do_query_quests(self, ctx, action, changes):
        return self._query(ctx, action, changes, "quests")

    def _query(
        self, ctx: RuleContext, action: Action, changes: ChangeSet, kind: str
    ) -> tuple[ActionOutcome, ChangeSet]:
        return ActionOutcome(
            action_type=action.action_type,
            success=True,
            summary_key=f"query_{kind}",
            time_cost_minutes=0,
            facts={"query": kind},
            importance=0.0,
        ), changes

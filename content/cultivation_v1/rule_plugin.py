"""Cultivation-specific rules behind the engine Rule Plugin API."""

from __future__ import annotations

from engine.actions.schema import Action, ActionOutcome, RuleResult
from engine.core import mutations as mut
from engine.core.mutations import ChangeSet
from engine.core.types import ActionType, Visibility
from engine.events.builder import EventBuilder, witnesses_for
from engine.rules.base import RuleContext, clamp

from .domain_rules import CultivationRules


class CultivationRulePlugin:
    key = "cultivation"
    api_version = "1"
    handled_actions = frozenset({ActionType.CULTIVATE, ActionType.BREAKTHROUGH})

    def validate_action(self, ctx: RuleContext, action: Action) -> RuleResult:
        actor = ctx.state.character_by_id(action.actor_id) or ctx.state.player
        if action.action_type is ActionType.CULTIVATE:
            minutes = action.duration_minutes or int(
                ctx.rule("time_costs.CULTIVATE.default", 240)
            )
            return CultivationRules.validate_cultivate(ctx, actor, minutes)
        return CultivationRules.validate_breakthrough(ctx, actor)

    def resolve_action(
        self,
        ctx: RuleContext,
        action: Action,
        rule_result: RuleResult,
        events: EventBuilder,
    ) -> tuple[ActionOutcome, ChangeSet]:
        if action.action_type is ActionType.CULTIVATE:
            return self._resolve_cultivate(ctx, action, events)
        return self._resolve_breakthrough(ctx, action, events)

    def _resolve_cultivate(
        self, ctx: RuleContext, action: Action, events: EventBuilder
    ) -> tuple[ActionOutcome, ChangeSet]:
        changes = ChangeSet()
        actor = ctx.state.character_by_id(action.actor_id) or ctx.state.player
        minutes = action.duration_minutes or int(
            ctx.rule("time_costs.CULTIVATE.default", 240)
        )
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
        regen = float(ctx.rule("combat.spiritual_power_regen_per_hour", 0.08)) * (
            minutes / 60.0
        )
        new_sp = min(
            actor.max_spiritual_power,
            int(actor.spiritual_power + actor.max_spiritual_power * regen),
        )
        if new_sp != actor.spiritual_power:
            changes.add(
                mut.character_field(
                    actor.id,
                    "spiritual_power",
                    actor.spiritual_power,
                    new_sp,
                    reason="cultivation",
                )
            )
        facts = {
            "minutes": minutes,
            "progress_before": round(gain.progress_before, 4),
            "progress_after": round(gain.progress_after, 4),
            "gain": round(gain.xp_ratio, 4),
            "diminished": gain.diminished,
            "breakdown": gain.breakdown,
            "ready_for_breakthrough": gain.progress_after >= 0.999,
        }
        importance = ctx.pack.event_importance("CULTIVATION_SESSION")
        visibility = Visibility(ctx.pack.event_visibility("CULTIVATION_SESSION"))
        changes.add_event(
            events.build(
                "CULTIVATION_SESSION",
                actor_id=action.actor_id,
                location_id=ctx.state.player.location_id,
                payload=facts,
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
                success=True,
                summary_key="CULTIVATE",
                time_cost_minutes=minutes,
                facts=facts,
                importance=importance,
            ),
            changes,
        )

    def _resolve_breakthrough(
        self, ctx: RuleContext, action: Action, events: EventBuilder
    ) -> tuple[ActionOutcome, ChangeSet]:
        changes = ChangeSet()
        actor = ctx.state.character_by_id(action.actor_id) or ctx.state.player
        ladder = ctx.pack.realms
        minutes = action.duration_minutes or int(
            ctx.rule("time_costs.BREAKTHROUGH.default", 1440)
        )
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
                    mut.character_field(
                        actor.id, "realm", actor.realm, odds.to_realm, reason="breakthrough"
                    ),
                    mut.character_field(
                        actor.id,
                        "realm_stage",
                        actor.realm_stage,
                        odds.to_stage,
                        reason="breakthrough",
                    ),
                    mut.character_field(
                        actor.id,
                        "cultivation_progress",
                        actor.cultivation_progress,
                        0.0,
                        reason="breakthrough",
                    ),
                    mut.character_field(
                        actor.id,
                        "max_health",
                        actor.max_health,
                        new_max_hp,
                        reason="breakthrough",
                    ),
                    mut.character_field(
                        actor.id, "health", actor.health, new_max_hp, reason="breakthrough"
                    ),
                    mut.character_field(
                        actor.id,
                        "max_spiritual_power",
                        actor.max_spiritual_power,
                        new_max_sp,
                        reason="breakthrough",
                    ),
                    mut.character_field(
                        actor.id,
                        "spiritual_power",
                        actor.spiritual_power,
                        new_max_sp,
                        reason="breakthrough",
                    ),
                    mut.character_field(
                        actor.id, "bottleneck", actor.bottleneck, 0.0, reason="breakthrough"
                    ),
                    mut.character_field(
                        actor.id,
                        "mental_state",
                        actor.mental_state,
                        round(
                            clamp(
                                actor.mental_state
                                + float(
                                    ctx.rule(
                                        "breakthrough.success.mental_state_gain", 0.1
                                    )
                                ),
                                0.0,
                                1.0,
                            ),
                            4,
                        ),
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
            visibility = Visibility(ctx.pack.event_visibility("BREAKTHROUGH"))
            changes.add_event(
                events.build(
                    "BREAKTHROUGH",
                    actor_id=actor.id,
                    location_id=actor.location_id,
                    before=before,
                    after=after,
                    causes=[f"cultivation:{minutes}m"]
                    + ([f"pill_bonus:{pill_bonus}"] if pill_bonus else []),
                    payload=facts,
                    world_minute=ctx.now,
                    rng_seed=ctx.rng.seed_hex,
                    importance=ctx.pack.event_importance("BREAKTHROUGH"),
                    witnesses=witnesses_for(
                        visibility, ctx.state.present_characters, actor.id
                    ),
                )
            )
            return (
                ActionOutcome(
                    action_type=action.action_type,
                    success=True,
                    summary_key="BREAKTHROUGH_SUCCESS",
                    time_cost_minutes=minutes,
                    facts=facts,
                    importance=ctx.pack.event_importance("BREAKTHROUGH"),
                ),
                changes,
            )

        penalties = CultivationRules.failure_penalties(ctx, actor)
        health_loss = int(actor.max_health * penalties["health_loss_ratio"])
        new_health = max(1, actor.health - health_loss)
        new_injuries = round(
            clamp(actor.injuries + penalties["injury_gain"], 0.0, 1.0), 4
        )
        new_mental = round(
            clamp(actor.mental_state - penalties["mental_state_loss"], 0.0, 1.0), 4
        )
        bottleneck_cap = float((ladder.bottleneck or {}).get("max", 0.6))
        new_bottleneck = round(
            clamp(actor.bottleneck + penalties["bottleneck_gain"], 0.0, bottleneck_cap),
            4,
        )
        changes.extend(
            [
                mut.character_field(
                    actor.id,
                    "health",
                    actor.health,
                    new_health,
                    reason="breakthrough_failed",
                ),
                mut.character_field(
                    actor.id,
                    "injuries",
                    actor.injuries,
                    new_injuries,
                    reason="breakthrough_failed",
                ),
                mut.character_field(
                    actor.id,
                    "mental_state",
                    actor.mental_state,
                    new_mental,
                    reason="breakthrough_failed",
                ),
                mut.character_field(
                    actor.id,
                    "bottleneck",
                    actor.bottleneck,
                    new_bottleneck,
                    reason="breakthrough_failed",
                ),
            ]
        )
        died = (
            ctx.rng.chance(penalties["death_chance"])
            if penalties["death_chance"] > 0
            else False
        )
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
            events.build(
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
        return (
            ActionOutcome(
                action_type=action.action_type,
                success=False,
                summary_key="BREAKTHROUGH_FAILED",
                time_cost_minutes=minutes,
                facts=facts,
                importance=ctx.pack.event_importance("BREAKTHROUGH_FAILED"),
            ),
            changes,
        )

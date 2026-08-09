"""RuleEngine - the deterministic gate every action passes through.

If this says no, nothing downstream may say yes (Prompt section 8).
"""

from __future__ import annotations

from engine.actions.schema import Action, RuleResult
from engine.core.types import QUERY_ACTIONS, ActionType, ReasonCode
from engine.rules.base import RuleContext
from engine.rules.combat import CombatRules, DetectionRules, SkillRules
from engine.rules.cultivation import CultivationRules
from engine.rules.economy import EconomyRules, InventoryRules
from engine.rules.interaction import FactionRules, InteractionRules
from engine.rules.movement import LocationRules, MovementRules, TimeRules


class RuleEngine:
    """Aggregates the twelve rule families behind one entry point."""

    movement = MovementRules
    location = LocationRules
    time = TimeRules
    cultivation = CultivationRules
    combat = CombatRules
    skills = SkillRules
    detection = DetectionRules
    inventory = InventoryRules
    economy = EconomyRules
    interaction = InteractionRules
    faction = FactionRules

    def validate_action(self, ctx: RuleContext, action: Action) -> RuleResult:
        state = ctx.state
        actor = state.character_by_id(action.actor_id) or state.player
        if not actor.alive:
            return RuleResult.deny(ReasonCode.ACTOR_DEAD, "the actor is dead")

        at = action.action_type
        if at in QUERY_ACTIONS:
            return RuleResult.ok(query=True)

        duration_check = TimeRules.validate_duration(ctx, action.duration_minutes)
        if not duration_check.allowed:
            return duration_check

        if at is ActionType.MOVE:
            return MovementRules.validate_action(ctx, action)

        if at in (ActionType.TALK, ActionType.ASK, ActionType.CONVERSATION, ActionType.FOLLOW):
            target = state.character_by_id(action.target_id)
            return InteractionRules.validate_interaction(ctx, actor, target)

        if at is ActionType.GIVE_ITEM:
            target = state.character_by_id(action.target_id)
            social = InteractionRules.validate_interaction(ctx, actor, target)
            if not social.allowed:
                return social
            return InventoryRules.validate_has_item(
                ctx, state.inventory, action.item_key, action.quantity
            )

        if at is ActionType.ATTACK:
            target = state.character_by_id(action.target_id)
            check = CombatRules.validate_attack(ctx, actor, target)
            if not check.allowed:
                return check
            assert target is not None
            faction_check = FactionRules.validate_faction_action(ctx, actor, target)
            if not faction_check.allowed:
                return faction_check
            if action.skill_key:
                return self._validate_skill(ctx, action)
            return RuleResult.ok()

        if at is ActionType.USE_SKILL:
            return self._validate_skill(ctx, action)

        if at is ActionType.USE_ITEM:
            return InventoryRules.validate_use_item(ctx, actor, state.inventory, action.item_key)

        if at in (ActionType.DROP, ActionType.SELL):
            if at is ActionType.SELL:
                return EconomyRules.validate_sale(
                    ctx, state.inventory, action.item_key, action.quantity
                )
            return InventoryRules.validate_has_item(
                ctx, state.inventory, action.item_key, action.quantity
            )

        if at is ActionType.BUY:
            if not state.present_characters:
                return RuleResult.deny(ReasonCode.NO_MERCHANT_HERE, "nobody here is selling")
            price = EconomyRules.calculate_price(
                ctx, action.item_key or "", buying=True, reputation=actor.reputation.global_
            )
            return EconomyRules.validate_purchase(
                ctx, state.inventory, action.item_key, action.quantity, price
            )

        if at is ActionType.CULTIVATE:
            minutes = action.duration_minutes or int(ctx.rule("time_costs.CULTIVATE.default", 240))
            return CultivationRules.validate_cultivate(ctx, actor, minutes)

        if at is ActionType.BREAKTHROUGH:
            return CultivationRules.validate_breakthrough(ctx, actor)

        if at is ActionType.STEAL:
            target = state.character_by_id(action.target_id)
            if target is None:
                return RuleResult.deny(ReasonCode.TARGET_NOT_FOUND, "nobody to steal from")
            if not target.alive:
                return RuleResult.ok()  # looting the dead is allowed
            return InteractionRules.validate_interaction(ctx, actor, target)

        if at in (ActionType.ACCEPT_QUEST, ActionType.REJECT_QUEST):
            if action.quest_id is None:
                return RuleResult.deny(ReasonCode.QUEST_NOT_FOUND, "no such task")
            quest = next((q for q in state.active_quests if q.id == action.quest_id), None)
            if quest is None:
                return RuleResult.deny(ReasonCode.QUEST_NOT_FOUND, "no such task")
            if quest.status != "offered":
                return RuleResult.deny(
                    ReasonCode.QUEST_NOT_OFFERED, "task is not on offer", status=quest.status
                )
            return RuleResult.ok(quest_key=quest.key)

        if at is ActionType.PICKUP:
            if not action.item_key or ctx.pack.item(action.item_key) is None:
                return RuleResult.deny(ReasonCode.ITEM_NOT_HERE, "nothing like that here")
            return InventoryRules.validate_capacity(ctx, state.inventory, action.item_key)

        # OBSERVE / SEARCH / HIDE / DEFEND / REST / WAIT / CUSTOM all always resolve.
        return RuleResult.ok()

    # ------------------------------------------------------------------
    def _validate_skill(self, ctx: RuleContext, action: Action) -> RuleResult:
        state = ctx.state
        actor = state.character_by_id(action.actor_id) or state.player
        skill_key = action.skill_key or ""
        row = state.skill_row(skill_key)
        return SkillRules.validate_use(
            ctx,
            actor,
            skill_key,
            learned=row is not None,
            last_used_minute=row.last_used_minute if row else -(10**9),
        )

    def available_actions(self, ctx: RuleContext, actor_id: str) -> list[str]:
        """Whitelist handed to NPC agents so they cannot invent capabilities."""
        state = ctx.state
        actor = state.character_by_id(actor_id)
        if actor is None or not actor.alive:
            return []
        allowed: list[str] = [
            ActionType.OBSERVE,
            ActionType.WAIT,
            ActionType.DEFEND,
            ActionType.HIDE,
            ActionType.MOVE,
            ActionType.REST,
        ]
        others = [c for c in state.present_characters if c.id != actor_id and c.alive]
        if state.player.alive and state.player.id != actor_id:
            others = [*others, state.player]
        if others:
            allowed += [
                ActionType.TALK,
                ActionType.ASK,
                ActionType.CONVERSATION,
                ActionType.ATTACK,
                ActionType.FOLLOW,
                ActionType.GIVE_ITEM,
            ]
        return [str(a) for a in allowed]

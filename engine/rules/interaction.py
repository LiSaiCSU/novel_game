"""InteractionRules and FactionRules (Prompt sections 38, 39).

Social outcomes are deliberately *not* a charisma check. Relationship state,
personality, what the target actually knows, the size of the ask and the risk
it carries all move the number.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.actions.schema import RuleResult
from engine.core.models import Character, Faction, Relationship
from engine.core.types import ReasonCode, RequestSize
from engine.rules.base import RuleContext, clamp


@dataclass(slots=True)
class SocialOdds:
    chance: float
    hard_refusal: bool
    breakdown: dict[str, float]
    reasons: list[str]


class InteractionRules:
    @staticmethod
    def validate_interaction(
        ctx: RuleContext, actor: Character, target: Character | None
    ) -> RuleResult:
        if not actor.alive:
            return RuleResult.deny(ReasonCode.ACTOR_DEAD, "the dead do not speak")
        if target is None:
            return RuleResult.deny(ReasonCode.TARGET_NOT_FOUND, "no such person here")
        if not target.alive:
            return RuleResult.deny(ReasonCode.TARGET_DEAD, "that person is dead")
        if actor.location_id != target.location_id:
            return RuleResult.deny(
                ReasonCode.TARGET_NOT_PRESENT,
                "that person is elsewhere",
                target_key=target.key,
            )
        return RuleResult.ok()

    @staticmethod
    def calculate_probability(
        ctx: RuleContext,
        actor: Character,
        target: Character,
        relationship: Relationship | None,
        *,
        request_size: RequestSize = RequestSize.TRIVIAL,
        risk_to_target: float = 0.0,
        violates_values: bool = False,
        violates_taboo: bool = False,
        method: str | None = None,
        actor_reputation: float = 0.0,
    ) -> SocialOdds:
        cfg = ctx.rule("social", {}) or {}
        weights = cfg.get("weights", {}) or {}
        reasons: list[str] = []

        chance = float(cfg.get("base_success", 0.25))
        breakdown: dict[str, float] = {"base": chance}

        rel = relationship
        if rel is not None:
            for dim in ("trust", "affection", "respect", "fear", "familiarity", "hatred", "suspicion"):
                contribution = float(getattr(rel, dim, 0)) * float(weights.get(dim, 0.0))
                chance += contribution
                if abs(contribution) >= 0.02:
                    breakdown[f"rel_{dim}"] = round(contribution, 4)
        else:
            penalty = float(cfg.get("first_meeting_penalty", 0.2))
            chance -= penalty
            breakdown["first_meeting"] = -penalty
            reasons.append("first_meeting")

        if rel is not None and rel.is_stranger():
            penalty = float(cfg.get("first_meeting_penalty", 0.2))
            chance -= penalty
            breakdown["first_meeting"] = -penalty
            reasons.append("first_meeting")

        charisma_term = (actor.charisma - 10) * float(weights.get("charisma", 0.01))
        chance += charisma_term
        breakdown["charisma"] = round(charisma_term, 4)

        rep_term = actor_reputation * float(weights.get("reputation", 0.0))
        chance += rep_term
        if abs(rep_term) >= 0.01:
            breakdown["reputation"] = round(rep_term, 4)

        size_penalty = float((cfg.get("request_size_penalty", {}) or {}).get(str(request_size), 0.0))
        chance -= size_penalty
        breakdown["request_size"] = -size_penalty
        if size_penalty >= 0.4:
            reasons.append("large_request")

        risk_penalty = clamp(risk_to_target, 0.0, 1.0) * float(cfg.get("risk_penalty_weight", 0.5))
        chance -= risk_penalty
        if risk_penalty:
            breakdown["risk"] = -round(risk_penalty, 4)
            reasons.append("risky_for_target")

        if violates_values:
            penalty = float(cfg.get("value_conflict_penalty", 0.4))
            chance -= penalty
            breakdown["value_conflict"] = -penalty
            reasons.append("conflicts_with_values")

        # personality shifts the baseline: cautious people say no more often
        caution = target.personality.trait("cautious", 0.5)
        caution_term = -(caution - 0.5) * 0.2
        chance += caution_term
        breakdown["target_caution"] = round(caution_term, 4)
        risk_tolerance_term = (target.personality.risk_tolerance - 0.5) * 0.15
        chance += risk_tolerance_term
        breakdown["target_risk_tolerance"] = round(risk_tolerance_term, 4)

        if method == "intimidate" or method == "threaten":
            fear_term = (float(getattr(rel, "fear", 0)) if rel else 0.0) * 0.004
            gap = ctx.pack.realms.realm_gap(actor.realm, target.realm)
            gap_term = gap * 0.12
            chance += fear_term + gap_term
            breakdown["intimidation"] = round(fear_term + gap_term, 4)
        if method == "bribe":
            greed = target.personality.trait("greedy", 0.3)
            chance += (greed - 0.3) * 0.3
            breakdown["greed"] = round((greed - 0.3) * 0.3, 4)

        hard = violates_taboo and bool(cfg.get("taboo_hard_refuse", True))
        if hard:
            reasons.append("violates_taboo")
            chance = 0.0

        chance = clamp(chance, float(cfg.get("min", 0.01)), float(cfg.get("max", 0.95)))
        return SocialOdds(chance=chance, hard_refusal=hard, breakdown=breakdown, reasons=reasons)

    @staticmethod
    def request_conflicts(target: Character, goal_type: str, topic: str | None) -> tuple[bool, bool]:
        """(violates_values, violates_taboo) for a request against a character."""
        haystack = f"{goal_type} {topic or ''}".lower()
        taboo = any(t.lower() in haystack for t in target.personality.taboos if t)
        values_conflict = False
        for value in target.personality.values:
            if not value:
                continue
            if value.lower() in ("loyalty", "sect_loyalty") and "betray" in haystack:
                values_conflict = True
            if value.lower() == "law" and "bribe" in haystack:
                values_conflict = True
        return values_conflict, taboo

    @staticmethod
    def calculate_deception_detection(
        ctx: RuleContext, deceiver: Character, target: Character, relationship: Relationship | None
    ) -> float:
        cfg = ctx.rule("social.deception_detection", {}) or {}
        chance = float(cfg.get("base", 0.35))
        chance += target.perception * float(cfg.get("perception_weight", 0.02))
        chance += target.intelligence * float(cfg.get("intelligence_weight", 0.015))
        if relationship is not None:
            chance += relationship.suspicion * float(cfg.get("suspicion_weight", 0.004))
        chance -= deceiver.charisma * 0.012
        return clamp(chance, 0.02, 0.98)


class FactionRules:
    @staticmethod
    def are_enemies(a: Faction | None, b: Faction | None) -> bool:
        if a is None or b is None:
            return False
        return b.key in a.enemies or a.key in b.enemies

    @staticmethod
    def are_allied(a: Faction | None, b: Faction | None) -> bool:
        if a is None or b is None:
            return False
        return b.key in a.alliances or a.key in b.alliances

    @staticmethod
    def validate_faction_action(
        ctx: RuleContext, actor: Character, target: Character
    ) -> RuleResult:
        """Blocks actions a faction would forbid outright (e.g. striking one's own leadership)."""
        if not actor.faction_key or actor.faction_key != target.faction_key:
            return RuleResult.ok()
        faction = ctx.state.factions.get(actor.faction_key)
        if faction is None:
            return RuleResult.ok()
        if faction.leader_key and target.key == faction.leader_key:
            return RuleResult.deny(
                ReasonCode.FACTION_FORBIDS,
                "cannot openly move against one's own leadership",
                faction=faction.key,
            )
        return RuleResult.ok()

    @staticmethod
    def reputation_for(character: Character, faction_key: str | None) -> float:
        if not faction_key:
            return character.reputation.global_
        return character.reputation.by_faction.get(faction_key, character.reputation.global_)

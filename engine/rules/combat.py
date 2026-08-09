"""CombatRules, SkillRules and DetectionRules (Prompt sections 35, 37).

AI may pick tactics. Numbers are adjudicated here.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.actions.schema import RuleResult
from engine.contentpack.pack import ContentPack
from engine.core.models import Character, Skill
from engine.core.types import ReasonCode
from engine.rules.base import RuleContext, clamp, effective_power


def _skill(pack: ContentPack, key: str) -> Skill | None:
    raw = pack.skill(key)
    return Skill(**{**raw, "world_id": ""}) if raw else None


class SkillRules:
    @staticmethod
    def validate_use(
        ctx: RuleContext, character: Character, skill_key: str, learned: bool, last_used_minute: int
    ) -> RuleResult:
        raw = ctx.pack.skill(skill_key)
        if raw is None:
            return RuleResult.deny(ReasonCode.SKILL_NOT_LEARNED, f"no such skill {skill_key}")
        if not learned:
            return RuleResult.deny(
                ReasonCode.SKILL_NOT_LEARNED, f"{skill_key} has never been learned", skill=skill_key
            )
        ladder = ctx.pack.realms
        required_realm = str(raw.get("required_realm", "mortal"))
        required_stage = str(raw.get("required_stage", ladder.first_stage(required_realm).key))
        if not ladder.meets_requirement(
            character.realm, character.realm_stage, required_realm, required_stage
        ):
            return RuleResult.deny(
                ReasonCode.REALM_TOO_LOW,
                f"{skill_key} requires a higher tier",
                skill=skill_key,
                required_realm=required_realm,
                required_stage=required_stage,
                actual_realm=character.realm,
                actual_stage=character.realm_stage,
            )
        cost = int(raw.get("spiritual_cost", 0))
        if character.spiritual_power < cost:
            return RuleResult.deny(
                ReasonCode.INSUFFICIENT_SPIRITUAL_POWER,
                "not enough spiritual power",
                required=cost,
                available=character.spiritual_power,
            )
        cooldown = int(raw.get("cooldown_minutes", 0))
        if cooldown and ctx.now - last_used_minute < cooldown:
            return RuleResult.deny(
                ReasonCode.SKILL_ON_COOLDOWN,
                "skill is still cooling down",
                ready_at=last_used_minute + cooldown,
                now=ctx.now,
            )
        return RuleResult.ok(spiritual_cost=cost, power=float(raw.get("power", 0.0)))

    @staticmethod
    def can_learn(ctx: RuleContext, character: Character, skill_key: str) -> RuleResult:
        raw = ctx.pack.skill(skill_key)
        if raw is None:
            return RuleResult.deny(ReasonCode.SKILL_NOT_LEARNED, f"no such skill {skill_key}")
        ladder = ctx.pack.realms
        required_realm = str(raw.get("required_realm", "mortal"))
        required_stage = str(raw.get("required_stage", ladder.first_stage(required_realm).key))
        if not ladder.meets_requirement(
            character.realm, character.realm_stage, required_realm, required_stage
        ):
            return RuleResult.deny(ReasonCode.REALM_TOO_LOW, "tier too low to learn this")
        return RuleResult.ok()


@dataclass(slots=True)
class AttackResolution:
    hit: bool
    damage: int
    hit_chance: float
    hard_blocked: bool
    lethal: bool
    breakdown: dict[str, float]


class CombatRules:
    @staticmethod
    def validate_attack(
        ctx: RuleContext, attacker: Character, defender: Character | None
    ) -> RuleResult:
        if not attacker.alive:
            return RuleResult.deny(ReasonCode.ACTOR_DEAD, "the dead do not fight")
        if defender is None:
            return RuleResult.deny(ReasonCode.TARGET_NOT_FOUND, "no such target")
        if not defender.alive:
            return RuleResult.deny(ReasonCode.TARGET_DEAD, "target is already dead")
        if attacker.location_id != defender.location_id:
            return RuleResult.deny(
                ReasonCode.TARGET_NOT_PRESENT,
                "target is not in melee range",
                attacker_location=attacker.location_id,
                target_location=defender.location_id,
            )
        if attacker.health <= 0:
            return RuleResult.deny(ReasonCode.INSUFFICIENT_HEALTH, "too injured to attack")
        return RuleResult.ok()

    @staticmethod
    def calculate_hit_chance(ctx: RuleContext, attacker: Character, defender: Character) -> float:
        cfg = ctx.rule("combat.hit_chance", {}) or {}
        chance = float(cfg.get("base", 0.75))
        chance += (attacker.agility - defender.agility) * float(cfg.get("agility_diff_weight", 0.02))
        chance += (attacker.perception - defender.perception) * float(
            cfg.get("perception_diff_weight", 0.01)
        )
        gap = ctx.pack.realms.realm_gap(attacker.realm, defender.realm)
        chance += gap * 0.10
        return clamp(chance, float(cfg.get("min", 0.05)), float(cfg.get("max", 0.98)))

    @staticmethod
    def calculate_damage(
        ctx: RuleContext,
        attacker: Character,
        defender: Character,
        *,
        skill_key: str | None = None,
        skill_mastery: float = 0.0,
        defending: bool = False,
        equipment_power: float = 0.0,
    ) -> AttackResolution:
        cfg = ctx.rule("combat.damage", {}) or {}
        weights = ctx.rule("combat.power_formula_weights", {}) or {}
        ladder = ctx.pack.realms

        hit_chance = CombatRules.calculate_hit_chance(ctx, attacker, defender)
        hit = ctx.rng.chance(hit_chance)

        skill_power = 0.0
        if skill_key:
            raw = ctx.pack.skill(skill_key)
            if raw:
                skill_power = float(raw.get("power", 0.0))

        attack_power = (
            effective_power(ctx, attacker)
            + skill_power * float(weights.get("skill_power", 1.0)) * (1.0 + skill_mastery)
            + equipment_power * float(weights.get("equipment", 0.8))
        )
        defence = effective_power(ctx, defender) * 0.35

        gap = ladder.realm_gap(attacker.realm, defender.realm)
        hard_block_at = int(cfg.get("realm_gap_hard_block", 2))
        hard_blocked = gap <= -hard_block_at

        multiplier = float(cfg.get("realm_gap_multiplier_per_order", 3.0)) ** gap
        variance_spec = cfg.get("base_variance", {"min": 0.85, "max": 1.2})
        variance = ctx.rng.uniform(float(variance_spec["min"]), float(variance_spec["max"]))

        raw_damage = max(0.0, attack_power * multiplier - defence) * variance
        if defending:
            raw_damage *= 1.0 - float(cfg.get("defend_reduction", 0.45))
        if hard_blocked:
            raw_damage = defender.max_health * float(cfg.get("hard_block_damage_ratio", 0.01))

        damage = int(max(0, round(raw_damage))) if hit else 0
        lethal = hit and damage >= defender.health

        return AttackResolution(
            hit=hit,
            damage=damage,
            hit_chance=hit_chance,
            hard_blocked=hard_blocked,
            lethal=lethal,
            breakdown={
                "attack_power": round(attack_power, 2),
                "defence": round(defence, 2),
                "realm_gap": float(gap),
                "multiplier": round(multiplier, 4),
                "variance": round(variance, 3),
                "skill_power": skill_power,
            },
        )

    @staticmethod
    def calculate_flee_chance(ctx: RuleContext, fleer: Character, threat: Character) -> float:
        cfg = ctx.rule("combat.flee", {}) or {}
        chance = float(cfg.get("base_chance", 0.5))
        chance += (fleer.agility - threat.agility) * float(cfg.get("agility_diff_weight", 0.03))
        gap = ctx.pack.realms.realm_gap(threat.realm, fleer.realm)
        chance -= max(0, gap) * float(cfg.get("realm_gap_penalty", 0.25))
        return clamp(chance, 0.02, 0.98)


class DetectionRules:
    """Whether a covert action is noticed (Prompt section 8)."""

    @staticmethod
    def calculate_detection(
        ctx: RuleContext,
        actor: Character,
        observers: list[Character],
        *,
        concealment_bonus: float = 0.0,
    ) -> float:
        cfg = ctx.rule("detection", {}) or {}
        if not observers:
            return 0.0
        best = max(observers, key=lambda c: c.perception)
        chance = float(cfg.get("base", 0.5))
        chance += (best.perception - actor.agility) * float(cfg.get("perception_weight", 0.03))
        chance -= actor.agility * float(cfg.get("agility_weight", 0.02)) * 0.5
        chance += ctx.pack.realms.realm_gap(best.realm, actor.realm) * float(
            cfg.get("realm_order_weight", 0.15)
        )
        chance += max(0, len(observers) - 1) * float(cfg.get("crowd_bonus_per_person", 0.04))
        phase = ctx.state.time.phase_key
        if phase in ("night", "deep_night"):
            chance += float(cfg.get("night_modifier", -0.15))
        chance -= concealment_bonus
        return clamp(chance, float(cfg.get("min", 0.02)), float(cfg.get("max", 0.98)))

    @staticmethod
    def roll_detected(
        ctx: RuleContext,
        actor: Character,
        observers: list[Character],
        *,
        concealment_bonus: float = 0.0,
    ) -> tuple[bool, float]:
        chance = DetectionRules.calculate_detection(
            ctx, actor, observers, concealment_bonus=concealment_bonus
        )
        return ctx.rng.chance(chance), chance

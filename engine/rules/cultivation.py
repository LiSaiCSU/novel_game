"""CultivationRules (Prompt section 34).

The whole progression loop is arithmetic over content-pack numbers. The
narrative model may describe a breakthrough; it may never cause one.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.actions.schema import RuleResult
from engine.core.models import Character
from engine.core.types import ReasonCode
from engine.rules.base import RuleContext, clamp


@dataclass(slots=True)
class CultivationGain:
    xp_ratio: float
    progress_before: float
    progress_after: float
    minutes: int
    diminished: bool
    breakdown: dict[str, float]


@dataclass(slots=True)
class BreakthroughOdds:
    chance: float
    breakdown: dict[str, float]
    from_realm: str
    from_stage: str
    to_realm: str
    to_stage: str


class CultivationRules:
    # -- cultivating --------------------------------------------------------
    @staticmethod
    def validate_cultivate(ctx: RuleContext, character: Character, minutes: int) -> RuleResult:
        if not character.alive:
            return RuleResult.deny(ReasonCode.ACTOR_DEAD, "the dead do not cultivate")
        if character.health <= 0:
            return RuleResult.deny(ReasonCode.INSUFFICIENT_HEALTH, "too injured to cultivate")
        cap = int(ctx.rule("time_costs.SECLUSION_MAX_MINUTES", 1_555_200))
        if minutes > cap:
            return RuleResult.deny(
                ReasonCode.TIME_LIMIT_EXCEEDED, "seclusion too long", requested=minutes, cap=cap
            )
        if ctx.pack.realms.next_step(character.realm, character.realm_stage) is None:
            return RuleResult.deny(ReasonCode.ALREADY_AT_MAX_REALM, "no higher tier exists")
        return RuleResult.ok()

    @staticmethod
    def calculate_gain(ctx: RuleContext, character: Character, minutes: int) -> CultivationGain:
        cfg = ctx.rule("cultivation", {}) or {}
        ladder = ctx.pack.realms

        base_per_hour = float(cfg.get("base_xp_per_hour", 10))
        location = ctx.state.graph.by_id(character.location_id)
        density = float(location.spirit_density if location else 1.0)
        root = ladder.spiritual_root(character.spiritual_root)
        root_speed = float(root.get("speed", 1.0))

        mental = clamp(character.mental_state, 0.0, 1.0)
        mental_term = 1.0 + (mental - 0.5) * float(cfg.get("mental_state_weight", 0.5))
        injury_term = 1.0 - clamp(character.injuries, 0.0, 1.0) * float(
            cfg.get("injury_penalty_per_point", 0.6)
        )

        hours = minutes / 60.0
        diminish_after = float(cfg.get("diminishing_after_minutes", 4320))
        diminished = minutes > diminish_after
        if diminished:
            normal_hours = diminish_after / 60.0
            extra_hours = (minutes - diminish_after) / 60.0
            hours = normal_hours + extra_hours * float(cfg.get("diminishing_factor", 0.5))

        raw_xp = (
            base_per_hour
            * hours
            * (density ** float(cfg.get("spirit_density_weight", 1.0)))
            * (root_speed ** float(cfg.get("root_weight", 1.0)))
            * character.cultivation_speed
            * mental_term
            * max(0.05, injury_term)
        )

        needed = max(1, ladder.xp_required(character.realm))
        ratio = raw_xp / needed
        cap = float(cfg.get("max_xp_ratio_per_session", 0.85))
        remaining = max(0.0, 1.0 - character.cultivation_progress)
        gained = min(ratio, cap, remaining)

        return CultivationGain(
            xp_ratio=gained,
            progress_before=character.cultivation_progress,
            progress_after=clamp(character.cultivation_progress + gained, 0.0, 1.0),
            minutes=minutes,
            diminished=diminished,
            breakdown={
                "base_per_hour": base_per_hour,
                "effective_hours": round(hours, 3),
                "spirit_density": density,
                "root_speed": root_speed,
                "mental_term": round(mental_term, 3),
                "injury_term": round(injury_term, 3),
                "xp_needed": float(needed),
                "raw_ratio": round(ratio, 5),
            },
        )

    # -- breaking through ---------------------------------------------------
    @staticmethod
    def validate_breakthrough(ctx: RuleContext, character: Character) -> RuleResult:
        if not character.alive:
            return RuleResult.deny(ReasonCode.ACTOR_DEAD, "the dead do not advance")
        ladder = ctx.pack.realms
        step = ladder.next_step(character.realm, character.realm_stage)
        if step is None:
            return RuleResult.deny(ReasonCode.ALREADY_AT_MAX_REALM, "no higher tier exists")
        required_full = bool(ctx.rule("cultivation.breakthrough_requires_full_xp", True))
        if required_full and character.cultivation_progress < 0.999:
            return RuleResult.deny(
                ReasonCode.CULTIVATION_NOT_READY,
                "cultivation progress is not complete",
                progress=round(character.cultivation_progress, 4),
            )
        return RuleResult.ok(to_realm=step[0], to_stage=step[1])

    @staticmethod
    def calculate_breakthrough(
        ctx: RuleContext, character: Character, pill_bonus: float = 0.0, technique_grade: int = 0
    ) -> BreakthroughOdds:
        cfg = ctx.rule("breakthrough", {}) or {}
        ladder = ctx.pack.realms
        step = ladder.next_step(character.realm, character.realm_stage)
        to_realm, to_stage = step if step else (character.realm, character.realm_stage)

        base = ladder.realm(character.realm).breakthrough_base_chance
        # crossing into a whole new realm is the hard part; intra-realm stages are easier
        crossing = ladder.is_realm_boundary(character.realm, character.realm_stage)
        if not crossing:
            base = min(0.95, base * 1.8)

        root = ladder.spiritual_root(character.spiritual_root)
        root_mod = float(root.get("breakthrough_mod", 0.0))
        mental_band = ladder.mental_state_band(clamp(character.mental_state, 0.0, 1.0))
        mental_mod = float(mental_band.get("breakthrough_mod", 0.0))
        technique_mod = technique_grade * float(cfg.get("technique_bonus_per_grade", 0.04))
        foundation_mod = character.foundation_quality * float(
            cfg.get("foundation_quality_weight", 0.10)
        )
        injury_mod = -character.injuries * float(cfg.get("injury_penalty_per_point", 0.35))
        bottleneck_cfg = ladder.bottleneck or {}
        bottleneck_mod = -character.bottleneck * float(bottleneck_cfg.get("penalty_per_point", 0.5))

        chance = (
            base
            + root_mod
            + mental_mod
            + technique_mod
            + foundation_mod
            + pill_bonus
            + injury_mod
            + bottleneck_mod
        )
        chance = clamp(chance, float(cfg.get("min_chance", 0.02)), float(cfg.get("max_chance", 0.95)))

        return BreakthroughOdds(
            chance=chance,
            breakdown={
                "base": round(base, 4),
                "spiritual_root": root_mod,
                "mental_state": mental_mod,
                "technique": round(technique_mod, 4),
                "foundation": round(foundation_mod, 4),
                "pill": pill_bonus,
                "injury": round(injury_mod, 4),
                "bottleneck": round(bottleneck_mod, 4),
                "crossing_realm": 1.0 if crossing else 0.0,
            },
            from_realm=character.realm,
            from_stage=character.realm_stage,
            to_realm=to_realm,
            to_stage=to_stage,
        )

    @staticmethod
    def failure_penalties(ctx: RuleContext, character: Character) -> dict[str, float]:
        cfg = (ctx.rule("breakthrough.failure", {}) or {})
        rng = ctx.rng
        hp_spec = cfg.get("health_loss_ratio", {"min": 0.1, "max": 0.3})
        inj_spec = cfg.get("injury_gain", {"min": 0.05, "max": 0.2})
        mental_spec = cfg.get("mental_state_loss", {"min": 0.05, "max": 0.2})
        health_loss = rng.uniform(float(hp_spec["min"]), float(hp_spec["max"]))
        injury_gain = rng.uniform(float(inj_spec["min"]), float(inj_spec["max"]))
        mental_loss = rng.uniform(float(mental_spec["min"]), float(mental_spec["max"]))
        bottleneck_gain = float((ctx.pack.realms.bottleneck or {}).get("gain_on_failure", 0.12))
        death_p = float(cfg.get("backlash_death_chance_at_full_injury", 0.0)) * clamp(
            character.injuries + injury_gain, 0.0, 1.0
        )
        return {
            "health_loss_ratio": health_loss,
            "injury_gain": injury_gain,
            "mental_state_loss": mental_loss,
            "bottleneck_gain": bottleneck_gain,
            "death_chance": death_p,
        }

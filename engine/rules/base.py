"""Shared context and helpers for the rule families.

Rules are deterministic functions of (world state, content pack, RNG stream).
They never call an LLM and never write to a repository.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.contentpack.pack import ContentPack
from engine.core.models import Character
from engine.rng.game_rng import GameRNG
from engine.world.clock import WorldClock
from engine.world.state_view import WorldStateView


@dataclass(slots=True)
class RuleContext:
    pack: ContentPack
    state: WorldStateView
    rng: GameRNG

    @property
    def clock(self) -> WorldClock:
        return self.state.clock

    @property
    def now(self) -> int:
        return self.state.world.current_minute

    def rule(self, path: str, default=None):
        return self.pack.rule(path, default)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def stat_diff(a: Character, b: Character, stat: str) -> int:
    return int(getattr(a, stat, 10)) - int(getattr(b, stat, 10))


def time_cost(ctx: RuleContext, key: str, override: int | None = None) -> int:
    """Roll the time an action consumes, honouring the pack's bounds."""
    spec = ctx.rule(f"time_costs.{key}") or {}
    low = int(spec.get("min", 5))
    high = int(spec.get("max", max(low, 5)))
    if override is not None:
        return clamp_int(override, low, high)
    default = spec.get("default")
    if default is not None:
        return int(default)
    if high <= low:
        return low
    return ctx.rng.randint(low, high)


def effective_power(ctx: RuleContext, character: Character) -> float:
    """Raw combat power before skills and equipment (Prompt section 37)."""
    weights = ctx.rule("combat.power_formula_weights", {}) or {}
    ladder = ctx.pack.realms
    realm_power = ladder.power(character.realm, character.realm_stage)
    return (
        realm_power * float(weights.get("realm", 1.0))
        + character.strength * float(weights.get("strength", 0.5))
        + character.agility * float(weights.get("agility", 0.3))
    ) * (1.0 - clamp(character.injuries, 0.0, 0.9) * 0.5)

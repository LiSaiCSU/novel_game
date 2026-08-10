"""MovementRules, LocationRules and TimeRules."""

from __future__ import annotations

from engine.actions.schema import Action, RuleResult
from engine.core.types import ReasonCode
from engine.rules.base import RuleContext, time_cost


class LocationRules:
    """Whether a place exists, is open, and may be entered."""

    @staticmethod
    def validate_target(ctx: RuleContext, location_key: str | None) -> RuleResult:
        if not location_key:
            return RuleResult.deny(ReasonCode.LOCATION_NOT_FOUND, "no destination given")
        location = ctx.state.graph.by_key(location_key)
        if location is None:
            return RuleResult.deny(
                ReasonCode.LOCATION_NOT_FOUND, f"unknown location {location_key}", key=location_key
            )
        if not location.accessible:
            return RuleResult.deny(
                ReasonCode.LOCATION_LOCKED, f"{location.key} is closed", key=location_key
            )
        return RuleResult.ok(location_id=location.id, location_key=location.key)

    @staticmethod
    def danger_level(ctx: RuleContext, location_key: str) -> int:
        loc = ctx.state.graph.by_key(location_key)
        return loc.danger_level if loc else 0


class MovementRules:
    @staticmethod
    def validate_action(ctx: RuleContext, action: Action) -> RuleResult:
        state = ctx.state
        actor = state.character_by_id(action.actor_id) or state.player
        if not actor.alive:
            return RuleResult.deny(ReasonCode.ACTOR_DEAD, "the dead do not travel")

        target = state.graph.by_id(action.target_location_id)
        if target is None:
            return RuleResult.deny(ReasonCode.LOCATION_NOT_FOUND, "unknown destination")

        check = LocationRules.validate_target(ctx, target.key)
        if not check.allowed:
            return check

        origin = state.graph.by_id(actor.location_id)
        if origin is None:
            return RuleResult.deny(ReasonCode.LOCATION_NOT_FOUND, "actor has no location")
        if origin.key == target.key:
            return RuleResult.ok(minutes=0, path=[origin.key], same_location=True)

        route = state.graph.path(origin.key, target.key)
        if route is None:
            return RuleResult.deny(
                ReasonCode.LOCATION_UNREACHABLE,
                f"no route from {origin.key} to {target.key}",
                origin=origin.key,
                destination=target.key,
            )
        path, minutes = route
        return RuleResult.ok(minutes=minutes, path=path, hops=len(path) - 1)

    @staticmethod
    def resolve_cost(
        ctx: RuleContext,
        minutes: int,
        hops: int,
        *,
        origin_key: str = "",
        destination_key: str = "",
    ) -> int:
        """Local journeys use the short travel band; leaving the region is a trip.

        "Local" is about geography, not hop count. Walking three doors down
        inside one sect is three hops and ten minutes of graph cost; charging
        it the regional floor turned a stroll across the courtyard into half a
        day, which is very visible now that one turn can contain several moves.
        """
        local_max = int(ctx.rule("time_costs.MOVE_LOCAL.max", 60))
        stays_local = (
            ctx.state.graph.shares_region(origin_key, destination_key)
            if origin_key and destination_key
            else hops <= 1
        )
        if stays_local and minutes <= local_max:
            return max(minutes, int(ctx.rule("time_costs.MOVE_LOCAL.min", 10)))
        return max(minutes, int(ctx.rule("time_costs.MOVE_REGIONAL.min", 240)))


class TimeRules:
    """Every action costs world time (Prompt section 33)."""

    @staticmethod
    def cost_for(ctx: RuleContext, action: Action) -> int:
        key = str(action.action_type)
        if action.duration_minutes is not None:
            return time_cost(ctx, key, override=action.duration_minutes)
        return time_cost(ctx, key)

    @staticmethod
    def validate_duration(ctx: RuleContext, minutes: int | None) -> RuleResult:
        if minutes is None:
            return RuleResult.ok()
        cap = int(ctx.rule("time_costs.SECLUSION_MAX_MINUTES", 1_555_200))
        if minutes > cap:
            return RuleResult.deny(
                ReasonCode.TIME_LIMIT_EXCEEDED,
                f"cannot spend more than {cap} minutes at once",
                requested=minutes,
                cap=cap,
            )
        return RuleResult.ok()

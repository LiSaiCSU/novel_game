"""Reading and moving the pressure the player can see.

A clock is only useful if the interface, the narrator and the rules all read
it the same way. Everything that renders or advances one goes through here, so
a dial showing three of nine filled can never disagree with prose that says
there are six days left.
"""

from __future__ import annotations

from typing import Any

from engine.core import mutations as mut
from engine.core.models import StoryClock
from engine.core.mutations import StateChange
from engine.core.types import ClockKind, ClockStatus
from engine.world.state_view import WorldStateView

#: Clocks the player is allowed to see, in the order they should be read:
#: what runs out on its own first, then what is closing in, then what the
#: player is building toward.
_KIND_ORDER = {ClockKind.DEADLINE: 0, ClockKind.DANGER: 1, ClockKind.PROJECT: 2}


def visible_clocks(state: WorldStateView) -> list[StoryClock]:
    running = [
        clock
        for clock in state.clocks
        if clock.visible and clock.status is not ClockStatus.CLOSED
    ]
    return sorted(running, key=lambda clock: (_KIND_ORDER.get(clock.kind, 9), clock.key))


def clock_view(clock: StoryClock, state: WorldStateView) -> dict[str, Any]:
    """One clock, in the shape the player application draws."""
    minute = state.world.current_minute
    filled = clock.filled_at(minute)
    remaining = clock.remaining_minutes(minute)
    unit, count = state.clock.duration_parts(remaining) if remaining else ("", 0)
    template = (state.pack.narrative_templates.get("duration", {}) or {}).get(unit, "")
    return {
        "key": clock.key,
        "name": clock.name,
        "kind": str(clock.kind),
        "segments": clock.segments,
        "filled": filled,
        "complete": clock.is_complete(minute),
        "thread": clock.thread_key,
        "consequence": clock.consequence,
        "remaining_label": (
            template.replace("{n}", str(count)) if remaining and template else ""
        ),
    }


def clock_views(state: WorldStateView) -> list[dict[str, Any]]:
    return [clock_view(clock, state) for clock in visible_clocks(state)]


def clocks_for_prompt(state: WorldStateView) -> str:
    """The same dials, as lines the narrator and the director can read.

    Prose that ignores the pressure the interface is showing reads as though
    the two were written by different people, which is exactly what it is.
    The wording comes from the pack; the engine only knows the numbers.
    """
    templates = (state.pack.narrative_templates.get("clock", {}) or {})
    line = str(templates.get("line", "- {name} {filled}/{segments}{remaining}{consequence}"))
    kinds = dict(templates.get("kinds", {}) or {})
    rows = []
    for clock in visible_clocks(state):
        view = clock_view(clock, state)
        remaining = (
            str(templates.get("remaining", "")).replace("{duration}", view["remaining_label"])
            if view["remaining_label"]
            else ""
        )
        consequence = (
            str(templates.get("consequence", "")).replace("{consequence}", clock.consequence)
            if clock.consequence
            else ""
        )
        rows.append(
            line.replace("{kind}", str(kinds.get(str(clock.kind), str(clock.kind))))
            .replace("{name}", clock.name)
            .replace("{filled}", str(view["filled"]))
            .replace("{segments}", str(clock.segments))
            .replace("{remaining}", remaining)
            .replace("{consequence}", consequence)
        )
    return "\n".join(rows) or str(templates.get("none", "-"))


def advance(
    clock: StoryClock, state: WorldStateView, delta: int, reason: str
) -> list[StateChange]:
    """Move a clock by whole segments, and close it when it fills.

    Time-driven progress is derived rather than stored, so ``filled`` only ever
    carries what events put there; the stored value is clamped against the
    derived total to keep a clock from passing its own last segment.
    """
    if clock.status is not ClockStatus.RUNNING or delta == 0:
        return []
    minute = state.world.current_minute
    ceiling = clock.segments - clock.elapsed_segments(minute)
    stored = max(0, min(clock.filled + delta, max(0, ceiling)))
    if stored == clock.filled:
        return []
    payload: dict[str, Any] = {"filled": stored}
    if stored + clock.elapsed_segments(minute) >= clock.segments:
        payload["status"] = str(ClockStatus.FILLED)
    # StateChange copies the payload on validation, so it has to be complete
    # before the change is built.
    return [mut.clock_update(clock.id, payload, reason=reason)]


def close(clock: StoryClock, reason: str) -> StateChange:
    """Stop a clock that has stopped mattering, without marking it as landed."""
    return mut.clock_update(clock.id, {"status": str(ClockStatus.CLOSED)}, reason=reason)


def tick_completed(state: WorldStateView) -> list[StateChange]:
    """Mark deadline clocks that the world clock has just run out on.

    Nothing else notices a deadline passing: its segments fill from elapsed
    time, so without this pass it would sit at full forever, still ``running``,
    and the director would keep treating it as pressure that has yet to land.
    """
    minute = state.world.current_minute
    return [
        mut.clock_update(
            clock.id,
            {"status": str(ClockStatus.FILLED)},
            reason="clock_ran_out",
        )
        for clock in state.clocks
        if clock.status is ClockStatus.RUNNING and clock.is_complete(minute)
    ]

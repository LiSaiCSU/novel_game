"""Event construction (Prompt sections 17, 44).

The event log answers "why is the world like this?", so an event carries its
before/after state, its causes, its causal parents, and the RNG seed that
produced it.
"""

from __future__ import annotations

from typing import Any

from engine.contentpack.pack import ContentPack
from engine.core.models import Character, Event
from engine.core.types import Visibility


class EventBuilder:
    def __init__(self, pack: ContentPack, world_id: str, turn_id: str | None = None) -> None:
        self.pack = pack
        self.world_id = world_id
        self.turn_id = turn_id

    def build(
        self,
        event_type: str,
        *,
        actor_id: str | None = None,
        target_ids: list[str] | None = None,
        location_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        causes: list[str] | None = None,
        cause_event_ids: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        world_minute: int = 0,
        rng_seed: str | None = None,
        importance: float | None = None,
        visibility: Visibility | str | None = None,
        witnesses: list[str] | None = None,
    ) -> Event:
        return Event(
            world_id=self.world_id,
            turn_id=self.turn_id,
            event_type=event_type,
            actor_id=actor_id,
            target_ids=target_ids or [],
            location_id=location_id,
            before=before or {},
            after=after or {},
            causes=causes or [],
            cause_event_ids=cause_event_ids or [],
            payload=payload or {},
            world_minute=world_minute,
            rng_seed=rng_seed,
            importance=(
                float(importance)
                if importance is not None
                else self.pack.event_importance(event_type)
            ),
            visibility=Visibility(visibility or self.pack.event_visibility(event_type)),
            witnesses=witnesses or [],
        )


def witnesses_for(
    event_visibility: Visibility, present: list[Character], actor_id: str | None
) -> list[str]:
    """Who perceives an event. SECRET stays with the actor; PRIVATE with participants."""
    if event_visibility is Visibility.SECRET:
        return [actor_id] if actor_id else []
    if event_visibility is Visibility.PRIVATE:
        return [actor_id] if actor_id else []
    return [c.id for c in present if c.alive] + ([actor_id] if actor_id else [])

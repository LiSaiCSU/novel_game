"""State mutation vocabulary.

Nothing in the engine writes to a repository directly. Every change to the world
is expressed as a :class:`StateChange`, collected into a :class:`ChangeSet`,
checked by the ConsistencyGuard, and applied inside one transaction
(Prompt sections 18, 58, 63).

AI subsystems may only *propose*. Proposals become StateChanges here, after
validation and clamping - never before.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from engine.core.models import DirectorEvent, Event, Memory, RelationshipChange


class ChangeKind(StrEnum):
    #: The world gaining a part it did not have. A content pack cannot enumerate
    #: everything a player will reach for, so the world is allowed to grow -
    #: but only through this change, in the same transaction as everything else,
    #: which is what keeps the new part as real and as permanent as the rest.
    CHARACTER_SPAWN = "CHARACTER_SPAWN"
    LOCATION_SPAWN = "LOCATION_SPAWN"
    CHARACTER_FIELD = "CHARACTER_FIELD"
    CHARACTER_LOCATION = "CHARACTER_LOCATION"
    CHARACTER_DEATH = "CHARACTER_DEATH"
    CHARACTER_EMOTION = "CHARACTER_EMOTION"
    CHARACTER_GOALS = "CHARACTER_GOALS"
    RELATIONSHIP_DELTA = "RELATIONSHIP_DELTA"
    INVENTORY_ADD = "INVENTORY_ADD"
    INVENTORY_REMOVE = "INVENTORY_REMOVE"
    SKILL_LEARN = "SKILL_LEARN"
    SKILL_USED = "SKILL_USED"
    KNOWLEDGE_SET = "KNOWLEDGE_SET"
    MEMORY_ADD = "MEMORY_ADD"
    QUEST_STATUS = "QUEST_STATUS"
    FACTION_FIELD = "FACTION_FIELD"
    PLOT_THREAD_UPDATE = "PLOT_THREAD_UPDATE"
    #: A thread the content pack never wrote down, opened because the player
    #: went somewhere the author did not plan for.
    PLOT_THREAD_SPAWN = "PLOT_THREAD_SPAWN"
    CLOCK_SPAWN = "CLOCK_SPAWN"
    CLOCK_UPDATE = "CLOCK_UPDATE"
    WORLD_TIME = "WORLD_TIME"
    WORLD_TENSION = "WORLD_TENSION"
    LOCATION_FLAG = "LOCATION_FLAG"


class StateChange(BaseModel):
    """One atomic, reversible-in-principle change to the canonical world."""

    model_config = ConfigDict(extra="forbid")

    kind: ChangeKind
    target_id: str = ""
    field: str = ""
    before: Any = None
    after: Any = None
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""

    def describe(self) -> str:
        if self.field:
            return f"{self.kind}:{self.target_id}.{self.field} {self.before!r} -> {self.after!r}"
        return f"{self.kind}:{self.target_id} {self.payload!r}"


class ChangeSet(BaseModel):
    """Everything a single turn wants to commit, in one transaction."""

    model_config = ConfigDict(extra="forbid")

    changes: list[StateChange] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    relationship_changes: list[RelationshipChange] = Field(default_factory=list)
    memories: list[Memory] = Field(default_factory=list)
    director_events: list[DirectorEvent] = Field(default_factory=list)

    def add(self, change: StateChange) -> None:
        self.changes.append(change)

    def extend(self, changes: list[StateChange]) -> None:
        self.changes.extend(changes)

    def add_event(self, event: Event) -> None:
        self.events.append(event)

    def is_empty(self) -> bool:
        return not (
            self.changes
            or self.events
            or self.relationship_changes
            or self.memories
            or self.director_events
        )

    def by_kind(self, kind: ChangeKind) -> list[StateChange]:
        return [c for c in self.changes if c.kind is kind]

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for c in self.changes:
            counts[str(c.kind)] = counts.get(str(c.kind), 0) + 1
        return {
            "change_counts": counts,
            "events": [e.event_type for e in self.events],
            "relationship_changes": len(self.relationship_changes),
            "memories": len(self.memories),
            "director_events": len(self.director_events),
        }


# ---------------------------------------------------------------------------
# Constructors. These are the *only* sanctioned way to build a StateChange.
# ---------------------------------------------------------------------------
def character_spawn(character: Any, reason: str = "") -> StateChange:
    """Bring a character into existence. ``character`` is a Character model."""
    return StateChange(
        kind=ChangeKind.CHARACTER_SPAWN,
        target_id=character.id,
        payload={"character": character.model_dump(mode="json")},
        reason=reason,
    )


def location_spawn(location: Any, reason: str = "") -> StateChange:
    """Bring a location into existence. ``location`` is a Location model."""
    return StateChange(
        kind=ChangeKind.LOCATION_SPAWN,
        target_id=location.id,
        payload={"location": location.model_dump(mode="json")},
        reason=reason,
    )


def character_field(
    character_id: str, field: str, before: Any, after: Any, reason: str = ""
) -> StateChange:
    return StateChange(
        kind=ChangeKind.CHARACTER_FIELD,
        target_id=character_id,
        field=field,
        before=before,
        after=after,
        reason=reason,
    )


def character_move(character_id: str, before: str | None, after: str, reason: str = "") -> StateChange:
    return StateChange(
        kind=ChangeKind.CHARACTER_LOCATION,
        target_id=character_id,
        field="location_id",
        before=before,
        after=after,
        reason=reason,
    )


def character_death(character_id: str, reason: str, event_id: str | None = None) -> StateChange:
    return StateChange(
        kind=ChangeKind.CHARACTER_DEATH,
        target_id=character_id,
        field="alive",
        before=True,
        after=False,
        payload={"death_event_id": event_id},
        reason=reason,
    )


def character_emotion(character_id: str, emotion: dict[str, Any], reason: str = "") -> StateChange:
    return StateChange(
        kind=ChangeKind.CHARACTER_EMOTION,
        target_id=character_id,
        payload=emotion,
        reason=reason,
    )


def character_goals(
    character_id: str, payload: dict[str, Any], reason: str = ""
) -> StateChange:
    return StateChange(
        kind=ChangeKind.CHARACTER_GOALS,
        target_id=character_id,
        payload=payload,
        reason=reason,
    )


def relationship_delta(
    character_a_id: str, character_b_id: str, deltas: dict[str, int], reason: str
) -> StateChange:
    return StateChange(
        kind=ChangeKind.RELATIONSHIP_DELTA,
        target_id=character_a_id,
        payload={"other_id": character_b_id, "deltas": deltas},
        reason=reason,
    )


def inventory_add(character_id: str, item_key: str, quantity: int, reason: str = "") -> StateChange:
    return StateChange(
        kind=ChangeKind.INVENTORY_ADD,
        target_id=character_id,
        payload={"item_key": item_key, "quantity": quantity},
        reason=reason,
    )


def inventory_remove(
    character_id: str, item_key: str, quantity: int, reason: str = ""
) -> StateChange:
    return StateChange(
        kind=ChangeKind.INVENTORY_REMOVE,
        target_id=character_id,
        payload={"item_key": item_key, "quantity": quantity},
        reason=reason,
    )


def skill_learn(character_id: str, skill_key: str, reason: str = "") -> StateChange:
    return StateChange(
        kind=ChangeKind.SKILL_LEARN,
        target_id=character_id,
        payload={"skill_key": skill_key},
        reason=reason,
    )


def skill_used(character_id: str, skill_key: str, at_minute: int) -> StateChange:
    return StateChange(
        kind=ChangeKind.SKILL_USED,
        target_id=character_id,
        payload={"skill_key": skill_key, "at_minute": at_minute},
    )


def knowledge_set(
    character_id: str,
    fact_id: str,
    state: str,
    confidence: float,
    source: str,
    at_minute: int,
    source_character_id: str | None = None,
    reason: str = "",
) -> StateChange:
    return StateChange(
        kind=ChangeKind.KNOWLEDGE_SET,
        target_id=character_id,
        payload={
            "fact_id": fact_id,
            "knowledge_state": state,
            "confidence": confidence,
            "source": source,
            "source_character_id": source_character_id,
            "learned_at_minute": at_minute,
        },
        reason=reason,
    )


def quest_status(quest_id: str, before: str, after: str, reason: str = "") -> StateChange:
    return StateChange(
        kind=ChangeKind.QUEST_STATUS,
        target_id=quest_id,
        field="status",
        before=before,
        after=after,
        reason=reason,
    )


def faction_field(
    faction_id: str, field: str, before: Any, after: Any, reason: str = ""
) -> StateChange:
    return StateChange(
        kind=ChangeKind.FACTION_FIELD,
        target_id=faction_id,
        field=field,
        before=before,
        after=after,
        reason=reason,
    )


def plot_thread_update(thread_id: str, payload: dict[str, Any], reason: str = "") -> StateChange:
    return StateChange(
        kind=ChangeKind.PLOT_THREAD_UPDATE,
        target_id=thread_id,
        payload=payload,
        reason=reason,
    )


def plot_thread_spawn(thread: Any, reason: str = "") -> StateChange:
    """Open a storyline mid-game.

    The pack ships the threads its author imagined. A player who decides to
    take over the coaching inn instead of digging for their father is not off
    the rails - they have started a story the author did not write, and the
    director has to be able to see it, weigh it and push it like any other.
    """
    return StateChange(
        kind=ChangeKind.PLOT_THREAD_SPAWN,
        target_id=thread.id,
        payload=thread.model_dump(mode="json"),
        reason=reason,
    )


def clock_spawn(clock: Any, reason: str = "") -> StateChange:
    return StateChange(
        kind=ChangeKind.CLOCK_SPAWN,
        target_id=clock.id,
        payload=clock.model_dump(mode="json"),
        reason=reason,
    )


def clock_update(clock_id: str, payload: dict[str, Any], reason: str = "") -> StateChange:
    return StateChange(
        kind=ChangeKind.CLOCK_UPDATE,
        target_id=clock_id,
        payload=payload,
        reason=reason,
    )


def world_time(world_id: str, before: int, after: int, reason: str = "") -> StateChange:
    return StateChange(
        kind=ChangeKind.WORLD_TIME,
        target_id=world_id,
        field="current_minute",
        before=before,
        after=after,
        reason=reason,
    )


def world_tension(world_id: str, before: float, after: float, reason: str = "") -> StateChange:
    return StateChange(
        kind=ChangeKind.WORLD_TENSION,
        target_id=world_id,
        field="narrative_tension",
        before=before,
        after=after,
        reason=reason,
    )


def location_flag(location_id: str, payload: dict[str, Any], reason: str = "") -> StateChange:
    return StateChange(
        kind=ChangeKind.LOCATION_FLAG,
        target_id=location_id,
        payload=payload,
        reason=reason,
    )

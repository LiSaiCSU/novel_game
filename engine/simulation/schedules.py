"""NPC schedules (Prompt section 32).

Nobody stands in a doorway waiting for the player. Characters sleep, work,
patrol and travel according to their own day, and important characters pursue
goals on top of that.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.models import Character, Location
from engine.core.mutations import StateChange
from engine.core.types import Activity, CharacterType
from engine.world.clock import WorldTime
from engine.world.location_graph import LocationGraph


@dataclass(slots=True)
class ScheduledIntent:
    character: Character
    activity: Activity
    destination_key: str | None


class ScheduleService:
    def __init__(self, pack: ContentPack) -> None:
        self.pack = pack

    # ------------------------------------------------------------------
    def intent_for(self, character: Character, time: WorldTime) -> ScheduledIntent:
        slot = character.schedule.for_phase(time.phase_key)
        activity = slot.activity if slot else character.schedule.default
        destination = slot.location_key if slot else None
        return ScheduledIntent(
            character=character, activity=activity, destination_key=destination
        )

    def goal_override(
        self, character: Character, graph: LocationGraph
    ) -> str | None:
        """Important characters may abandon the routine for their own agenda."""
        if character.character_type is not CharacterType.MAJOR_NPC:
            return None
        if not character.short_term_goals:
            return None
        # Goal-directed movement is expressed in content as a schedule slot with
        # an explicit location; if none exists, the character keeps its routine.
        for slot in character.schedule.slots:
            if (
                slot.activity in (Activity.INVESTIGATE, Activity.TRAVEL)
                and slot.location_key
                and graph.by_key(slot.location_key) is not None
            ):
                return slot.location_key
        return None

    # ------------------------------------------------------------------
    def move_changes(
        self,
        characters: list[Character],
        graph: LocationGraph,
        time: WorldTime,
        *,
        exclude_ids: set[str] | None = None,
    ) -> list[StateChange]:
        """Where everyone should be right now, expressed as location changes."""
        excluded = exclude_ids or set()
        changes: list[StateChange] = []
        for character in characters:
            if not character.alive or character.id in excluded:
                continue
            if character.character_type is CharacterType.PLAYER:
                continue
            intent = self.intent_for(character, time)
            destination_key = intent.destination_key or self.goal_override(character, graph)
            if not destination_key:
                continue
            destination: Location | None = graph.by_key(destination_key)
            if destination is None or destination.id == character.location_id:
                continue
            changes.append(
                mut.character_move(
                    character.id,
                    character.location_id,
                    destination.id,
                    reason=f"schedule:{intent.activity}",
                )
            )
        return changes

    def activity_of(self, character: Character, time: WorldTime) -> Activity:
        return self.intent_for(character, time).activity

    def is_available(self, character: Character, time: WorldTime) -> bool:
        """A sleeping character is not going to answer questions."""
        return self.activity_of(character, time) is not Activity.SLEEP

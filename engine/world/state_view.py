"""WorldStateView - a read-only snapshot of everything a turn needs.

Loading this once at the top of a turn keeps the rest of the pipeline free of
ad-hoc queries, and makes it obvious exactly how much of the world any given
subsystem can see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.contentpack.pack import ContentPack
from engine.core.models import (
    Character,
    CharacterSkill,
    Faction,
    InventoryItem,
    Location,
    PlotThread,
    Quest,
    Relationship,
    World,
)
from engine.core.ports import UnitOfWork
from engine.world.clock import WorldClock, WorldTime
from engine.world.location_graph import LocationGraph


@dataclass(slots=True)
class WorldStateView:
    world: World
    pack: ContentPack
    clock: WorldClock
    time: WorldTime
    graph: LocationGraph
    player: Character
    location: Location | None
    present_characters: list[Character] = field(default_factory=list)
    factions: dict[str, Faction] = field(default_factory=dict)
    inventory: list[InventoryItem] = field(default_factory=list)
    known_skills: list[CharacterSkill] = field(default_factory=list)
    relationships: dict[str, Relationship] = field(default_factory=dict)
    active_quests: list[Quest] = field(default_factory=list)
    plot_threads: list[PlotThread] = field(default_factory=list)

    # -- helpers ------------------------------------------------------------
    def character_by_id(self, character_id: str | None) -> Character | None:
        if not character_id:
            return None
        if self.player.id == character_id:
            return self.player
        return next((c for c in self.present_characters if c.id == character_id), None)

    def character_by_key(self, key: str | None) -> Character | None:
        if not key:
            return None
        if self.player.key == key:
            return self.player
        return next((c for c in self.present_characters if c.key == key), None)

    def is_present(self, character_id: str) -> bool:
        return character_id == self.player.id or any(
            c.id == character_id for c in self.present_characters
        )

    def relationship_with(self, other_id: str) -> Relationship | None:
        return self.relationships.get(other_id)

    def inventory_quantity(self, item_key: str) -> int:
        return sum(row.quantity for row in self.inventory if row.item_key == item_key)

    def has_skill(self, skill_key: str) -> bool:
        return any(s.skill_key == skill_key for s in self.known_skills)

    def skill_row(self, skill_key: str) -> CharacterSkill | None:
        return next((s for s in self.known_skills if s.skill_key == skill_key), None)

    def location_key(self) -> str:
        return self.location.key if self.location else ""

    def faction_name(self, faction_key: str | None) -> str:
        """A faction's readable name. Keys are for the engine, not the reader."""
        if not faction_key:
            return ""
        faction = self.factions.get(faction_key)
        return faction.name if faction else faction_key

    def item_name(self, item_key: str) -> str:
        item = self.pack.item(item_key) or {}
        return str(item.get("name") or item_key)

    def scene_summary(self) -> dict[str, Any]:
        return {
            "location": {
                "key": self.location.key if self.location else None,
                "name": self.location.name if self.location else None,
                "description": self.location.description if self.location else "",
                "danger_level": self.location.danger_level if self.location else 0,
            },
            "time": self.time.as_dict(),
            "present_characters": [
                {
                    "id": c.id,
                    "key": c.key,
                    "name": c.display_name,
                    "realm": self.pack.realms.display(c.realm, c.realm_stage),
                    # The player reads this. Internal keys never leave here.
                    "faction": self.faction_name(c.faction_key),
                    "title": c.faction_rank or "",
                }
                for c in self.present_characters
            ],
            "player": {
                "id": self.player.id,
                "name": self.player.name,
                "realm": self.pack.realms.display(self.player.realm, self.player.realm_stage),
                "health": [self.player.health, self.player.max_health],
                "spiritual_power": [
                    self.player.spiritual_power,
                    self.player.max_spiritual_power,
                ],
                "cultivation_progress": round(self.player.cultivation_progress, 4),
                "injuries": round(self.player.injuries, 3),
                "mental_state": round(self.player.mental_state, 3),
                "attributes": self.player.attributes,
                "resources": self.player.resources,
                "progressions": self.player.progressions,
                "properties": self.player.properties,
            },
        }


async def build_world_state(
    uow: UnitOfWork, pack: ContentPack, world_id: str, player_id: str
) -> WorldStateView:
    world = await uow.worlds.get(world_id)
    if world is None:
        raise LookupError(f"world {world_id} not found")
    player = await uow.characters.get(player_id)
    if player is None:
        raise LookupError(f"player character {player_id} not found")

    locations = await uow.locations.list_for_world(world_id)
    graph = LocationGraph(locations)
    clock = WorldClock(world.calendar_config or pack.calendar)

    location = graph.by_id(player.location_id)
    present: list[Character] = []
    if player.location_id:
        present = [
            c
            for c in await uow.characters.list_at_location(world_id, player.location_id)
            if c.id != player.id
        ]

    factions = {f.key: f for f in await uow.factions.list_for_world(world_id)}
    inventory = await uow.items.list_inventory(player.id)
    skills = await uow.skills.list_for_character(player.id)
    relationships = {
        rel.character_b_id: rel for rel in await uow.relationships.list_for_character(player.id)
    }
    quests = await uow.quests.list_for_world(world_id)
    threads = await uow.plot_threads.list_for_world(world_id)

    return WorldStateView(
        world=world,
        pack=pack,
        clock=clock,
        time=clock.to_world_time(world.current_minute),
        graph=graph,
        player=player,
        location=location,
        present_characters=present,
        factions=factions,
        inventory=inventory,
        known_skills=skills,
        relationships=relationships,
        active_quests=quests,
        plot_threads=threads,
    )

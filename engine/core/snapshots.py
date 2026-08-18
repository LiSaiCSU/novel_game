"""Read models that cross repository boundaries in one database round trip."""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.core.models import (
    Character,
    CharacterSkill,
    Faction,
    InventoryItem,
    Location,
    PlotThread,
    Quest,
    Relationship,
    StoryClock,
    World,
)


@dataclass(slots=True)
class WorldStateSnapshot:
    """The complete canonical read set needed at the start of one turn."""

    world: World | None = None
    player: Character | None = None
    locations: list[Location] = field(default_factory=list)
    present_characters: list[Character] = field(default_factory=list)
    factions: list[Faction] = field(default_factory=list)
    inventory: list[InventoryItem] = field(default_factory=list)
    skills: list[CharacterSkill] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    quests: list[Quest] = field(default_factory=list)
    plot_threads: list[PlotThread] = field(default_factory=list)
    clocks: list[StoryClock] = field(default_factory=list)

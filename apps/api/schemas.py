"""API request/response DTOs. Kept separate from domain models on purpose."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from engine.orchestrator.turn import (
    DEFAULT_NARRATIVE_CHARS,
    MAX_NARRATIVE_CHARS,
    MIN_NARRATIVE_CHARS,
    StoryBeat,
)


class CreateWorldRequest(BaseModel):
    name: str | None = None
    world_seed: str | None = None
    content_pack: str | None = None


class WorldSummary(BaseModel):
    id: str
    name: str
    description: str = ""
    content_pack: str
    world_seed: str
    current_minute: int
    time_label: str
    narrative_tension: float
    character_count: int = 0
    location_count: int = 0


class CreateCharacterRequest(BaseModel):
    world_id: str
    name: str
    gender: str = "unspecified"
    age: int = Field(default=18, ge=18, le=80)
    background: str = ""
    spiritual_root: str | None = None
    stats: dict[str, int] = Field(default_factory=dict)


class CharacterSummary(BaseModel):
    id: str
    key: str
    name: str
    title: str | None = None
    character_type: str
    realm: str
    realm_display: str
    realm_stage: str
    cultivation_progress: float
    health: list[int]
    spiritual_power: list[int]
    location_key: str | None = None
    location_name: str | None = None
    faction_key: str | None = None
    alive: bool = True
    stats: dict[str, int] = Field(default_factory=dict)
    injuries: float = 0.0
    mental_state: float = 0.5


class StartGameRequest(BaseModel):
    world_id: str | None = None
    player_name: str = ""
    gender: str = "unspecified"
    age: int = Field(default=18, ge=18, le=80)
    background: str = ""
    world_seed: str | None = None
    session_seed: str = "session-1"
    narrative_max_chars: int = Field(
        default=DEFAULT_NARRATIVE_CHARS,
        ge=MIN_NARRATIVE_CHARS,
        le=MAX_NARRATIVE_CHARS,
    )


class StartGameResponse(BaseModel):
    session_id: str
    world_id: str
    player_character_id: str
    opening: str
    beat: StoryBeat | None = None
    state: dict[str, Any]


class ActionRequest(BaseModel):
    text: str
    idempotency_key: str | None = None
    debug: bool = False
    narrative_max_chars: int = Field(
        default=DEFAULT_NARRATIVE_CHARS,
        ge=MIN_NARRATIVE_CHARS,
        le=MAX_NARRATIVE_CHARS,
    )


class RelationshipView(BaseModel):
    with_character_id: str
    with_key: str
    with_name: str
    dimensions: dict[str, int]
    tags: list[str] = Field(default_factory=list)
    last_interaction_minute: int
    interaction_count: int


class MemoryView(BaseModel):
    id: str
    memory_type: str
    memory_tag: str
    summary: str
    importance: float
    emotional_valence: float
    created_at_minute: int
    related_characters: list[str] = Field(default_factory=list)


class InventoryView(BaseModel):
    item_key: str
    name: str
    item_type: str
    rarity: str
    quantity: int
    description: str = ""
    value: int = 0


class QuestView(BaseModel):
    key: str
    name: str
    status: str
    status_label: str = ""
    giver: str | None = None
    goal: dict[str, Any] = Field(default_factory=dict)
    expires_at_minute: int | None = None


class HistoryEntry(BaseModel):
    turn_id: str
    turn_number: int
    player_input: str
    narrative: str
    world_minute_after: int


class EventView(BaseModel):
    id: str
    event_type: str
    actor_id: str | None
    world_minute: int
    importance: float
    visibility: str
    summary: str = ""
    causes: list[str] = Field(default_factory=list)


class InspectorView(BaseModel):
    world: WorldSummary
    characters: list[CharacterSummary]
    factions: list[dict[str, Any]]
    plot_threads: list[dict[str, Any]]
    director_events: list[dict[str, Any]]
    recent_events: list[EventView]
    tension: dict[str, Any]


class CreateSaveRequest(BaseModel):
    name: str = ""


class SaveView(BaseModel):
    """One restore point, as the save list shows it."""

    id: str
    session_id: str
    world_id: str
    name: str = ""
    player_name: str = ""
    turn_number: int = 0
    time_label: str = ""
    location_name: str = ""
    excerpt: str = ""
    created_at: str | None = None


class OpeningView(BaseModel):
    """The story so far - what a client needs to rejoin a loaded session."""

    session_id: str
    world_id: str
    player_character_id: str
    chapters: list[str] = Field(default_factory=list)
    beat: StoryBeat | None = None
    state: dict[str, Any] = Field(default_factory=dict)

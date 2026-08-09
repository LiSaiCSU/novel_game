"""Domain models.

Pure data + tiny helpers. No persistence, no I/O, no content-pack literals.
Everything the world considers *true* is expressed here and nowhere else.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from engine.core.ids import new_id
from engine.core.types import (
    Activity,
    CharacterType,
    FactScope,
    KnowledgeSource,
    KnowledgeState,
    MemoryTag,
    MemoryType,
    QuestStatus,
    ThreadStatus,
    Visibility,
)

RELATIONSHIP_DIMENSIONS: tuple[str, ...] = (
    "affection",
    "trust",
    "respect",
    "fear",
    "hatred",
    "suspicion",
    "dependency",
    "familiarity",
)


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=False)


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------
class World(Base):
    id: str = Field(default_factory=new_id)
    name: str
    description: str = ""
    current_minute: int = 0
    calendar_config: dict[str, Any] = Field(default_factory=dict)
    world_seed: str = "seed"
    content_pack: str = ""
    rule_version: str = "1.0.0"
    narrative_tension: float = 20.0
    tension_history: list[float] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Location(Base):
    id: str = Field(default_factory=new_id)
    world_id: str = ""
    parent_id: str | None = None
    key: str
    name: str
    location_type: str = "wilderness"
    description: str = ""
    coordinates: dict[str, float] = Field(default_factory=dict)
    danger_level: int = 0
    spirit_density: float = 1.0
    faction_key: str | None = None
    accessible: bool = True
    travel_minutes: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Faction(Base):
    id: str = Field(default_factory=new_id)
    world_id: str = ""
    key: str
    name: str
    description: str = ""
    faction_type: str = "sect"
    headquarters_key: str | None = None
    resources: dict[str, float] = Field(default_factory=dict)
    member_count: int = 0
    territory: list[str] = Field(default_factory=list)
    military_power: float = 0.0
    reputation: float = 0.0
    leader_key: str | None = None
    alliances: list[str] = Field(default_factory=list)
    enemies: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    internal_conflicts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------
class Personality(Base):
    """Slow-moving. Explicitly *not* emotion (Prompt section 13)."""

    traits: dict[str, float] = Field(default_factory=dict)
    values: list[str] = Field(default_factory=list)
    taboos: list[str] = Field(default_factory=list)
    speech_style: str = ""
    risk_tolerance: float = 0.5

    def trait(self, name: str, default: float = 0.5) -> float:
        return float(self.traits.get(name, default))


class Emotion(Base):
    """Fast-moving. Reset/decays every few turns."""

    dominant: str = "neutral"
    valence: float = 0.0
    arousal: float = 0.2
    intensity: float = 0.3
    updated_at_minute: int = 0


class ScheduleSlot(Base):
    phase: str
    activity: Activity = Activity.WORK
    location_key: str | None = None


class Schedule(Base):
    default: Activity = Activity.WORK
    slots: list[ScheduleSlot] = Field(default_factory=list)

    def for_phase(self, phase: str) -> ScheduleSlot | None:
        for slot in self.slots:
            if slot.phase == phase:
                return slot
        return None


class Reputation(Base):
    global_: float = 0.0
    by_faction: dict[str, float] = Field(default_factory=dict)
    by_region: dict[str, float] = Field(default_factory=dict)


class Character(Base):
    id: str = Field(default_factory=new_id)
    world_id: str = ""
    key: str
    name: str
    title: str | None = None
    character_type: CharacterType = CharacterType.BACKGROUND
    age: int = 20
    gender: str = "unspecified"
    location_id: str | None = None
    location_key: str | None = None
    faction_key: str | None = None
    faction_rank: str | None = None

    realm: str = "mortal"
    realm_stage: str = "normal"
    cultivation_progress: float = 0.0
    cultivation_speed: float = 1.0
    spiritual_root: str = ""
    bottleneck: float = 0.0
    mental_state: float = 0.5
    foundation_quality: float = 0.5

    health: int = 100
    max_health: int = 100
    spiritual_power: int = 0
    max_spiritual_power: int = 0

    strength: int = 10
    agility: int = 10
    perception: int = 10
    intelligence: int = 10
    willpower: int = 10
    charisma: int = 10

    personality: Personality = Field(default_factory=Personality)
    background: str = ""
    long_term_goal: str = ""
    short_term_goals: list[str] = Field(default_factory=list)
    current_emotion: Emotion = Field(default_factory=Emotion)
    injuries: float = 0.0
    schedule: Schedule = Field(default_factory=Schedule)
    reputation: Reputation = Field(default_factory=Reputation)

    alive: bool = True
    death_event_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_player(self) -> bool:
        return self.character_type is CharacterType.PLAYER

    @property
    def display_name(self) -> str:
        return f"{self.title}{self.name}" if self.title else self.name


class Relationship(Base):
    """Directed: how ``character_a`` sees ``character_b`` (Prompt section 14)."""

    id: str = Field(default_factory=new_id)
    world_id: str = ""
    character_a_id: str
    character_b_id: str
    affection: int = 0
    trust: int = 0
    respect: int = 0
    fear: int = 0
    hatred: int = 0
    suspicion: int = 0
    dependency: int = 0
    familiarity: int = 0
    last_interaction_minute: int = 0
    interaction_count: int = 0
    tags: list[str] = Field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {dim: int(getattr(self, dim)) for dim in RELATIONSHIP_DIMENSIONS}

    def is_stranger(self) -> bool:
        return self.interaction_count == 0 and self.familiarity <= 0


class RelationshipChange(Base):
    """Audit row: every relationship movement has a cause (Prompt section 14)."""

    id: str = Field(default_factory=new_id)
    world_id: str = ""
    character_a_id: str
    character_b_id: str
    dimension: str
    before: int
    after: int
    delta: int
    reason: str
    event_id: str | None = None
    clamped: bool = False
    world_minute: int = 0


# ---------------------------------------------------------------------------
# Knowledge
# ---------------------------------------------------------------------------
class Fact(Base):
    """Objective truth. ``truth_value`` NEVER reaches an NPC prompt."""

    id: str = Field(default_factory=new_id)
    world_id: str = ""
    key: str
    statement: str
    truth_value: bool | None = True
    scope: FactScope = FactScope.WORLD
    sensitivity: float = 0.0
    subject_character_key: str | None = None
    related_characters: list[str] = Field(default_factory=list)
    created_at_minute: int = 0
    source_event_id: str | None = None


class CharacterKnowledge(Base):
    """What a specific character believes about a fact."""

    id: str = Field(default_factory=new_id)
    character_id: str
    fact_id: str
    knowledge_state: KnowledgeState = KnowledgeState.UNKNOWN
    confidence: float = 0.0
    source: KnowledgeSource = KnowledgeSource.SEED
    source_character_id: str | None = None
    learned_at_minute: int = 0
    notes: str = ""


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
class Memory(Base):
    id: str = Field(default_factory=new_id)
    world_id: str = ""
    owner_character_id: str
    memory_type: MemoryType = MemoryType.EPISODIC
    memory_tag: MemoryTag = MemoryTag.OTHER
    summary: str
    importance: float = 0.5
    emotional_valence: float = 0.0
    related_characters: list[str] = Field(default_factory=list)
    related_event_id: str | None = None
    related_location_id: str | None = None
    created_at_minute: int = 0
    last_recalled_minute: int = 0
    recall_count: int = 0
    decay: float = 1.0
    embedding: list[float] | None = None


# ---------------------------------------------------------------------------
# Items / skills / inventory
# ---------------------------------------------------------------------------
class Item(Base):
    id: str = Field(default_factory=new_id)
    world_id: str = ""
    key: str
    name: str
    item_type: str = "misc"
    rarity: str = "common"
    description: str = ""
    effects: dict[str, Any] = Field(default_factory=dict)
    value: int = 0
    stackable: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class InventoryItem(Base):
    id: str = Field(default_factory=new_id)
    character_id: str
    item_key: str
    quantity: int = 1
    equipped: bool = False
    bound: bool = False
    acquired_at_minute: int = 0


class Skill(Base):
    id: str = Field(default_factory=new_id)
    world_id: str = ""
    key: str
    name: str
    category: str = "attack"
    required_realm: str = "mortal"
    required_stage: str = "normal"
    spiritual_cost: int = 0
    cooldown_minutes: int = 0
    power: float = 0.0
    description: str = ""
    effects: dict[str, Any] = Field(default_factory=dict)


class CharacterSkill(Base):
    id: str = Field(default_factory=new_id)
    character_id: str
    skill_key: str
    mastery: float = 0.1
    learned_at_minute: int = 0
    last_used_minute: int = -10**9


# ---------------------------------------------------------------------------
# Quests / events / plot
# ---------------------------------------------------------------------------
class Quest(Base):
    id: str = Field(default_factory=new_id)
    world_id: str = ""
    key: str
    name: str
    giver_character_key: str | None = None
    assignee_character_key: str | None = None
    status: QuestStatus = QuestStatus.OFFERED
    goal: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    participants: list[str] = Field(default_factory=list)
    rewards: dict[str, Any] = Field(default_factory=dict)
    failure_conditions: list[str] = Field(default_factory=list)
    expires_at_minute: int | None = None
    world_consequences: dict[str, Any] = Field(default_factory=dict)
    plot_thread_key: str | None = None


class Event(Base):
    """Append-only. Never updated, never deleted (Prompt section 17)."""

    id: str = Field(default_factory=new_id)
    world_id: str = ""
    turn_id: str | None = None
    event_type: str
    actor_id: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    location_id: str | None = None
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    causes: list[str] = Field(default_factory=list)
    cause_event_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    world_minute: int = 0
    rng_seed: str | None = None
    importance: float = 0.1
    visibility: Visibility = Visibility.LOCAL
    witnesses: list[str] = Field(default_factory=list)


class PlotThread(Base):
    id: str = Field(default_factory=new_id)
    world_id: str = ""
    key: str
    name: str
    status: ThreadStatus = ThreadStatus.ACTIVE
    importance: float = 0.5
    stage: int = 0
    participants: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    related_facts: list[str] = Field(default_factory=list)
    last_advanced_minute: int = 0
    next_beat_hint: str = ""
    escalation_pressure: float = 0.1
    metadata: dict[str, Any] = Field(default_factory=dict)


class NarrativeSegment(Base):
    id: str = Field(default_factory=new_id)
    session_id: str
    turn_id: str | None = None
    kind: str = "scene"
    text: str = ""
    world_minute: int = 0


class GameSession(Base):
    id: str = Field(default_factory=new_id)
    world_id: str
    player_character_id: str
    session_seed: str = "session"
    status: str = "active"
    turn_number: int = 0

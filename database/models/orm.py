"""ORM models. Mirrors docs/DATA_MODEL.md exactly."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, JSONType, TimestampMixin, utcnow


class WorldORM(TimestampMixin, Base):
    __tablename__ = "worlds"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str] = mapped_column(sa.Text, default="")
    current_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    calendar_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    world_seed: Mapped[str] = mapped_column(sa.String(120), default="seed")
    content_pack: Mapped[str] = mapped_column(sa.String(120), default="")
    release_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    playthrough_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    rule_version: Mapped[str] = mapped_column(sa.String(40), default="1.0.0")
    narrative_tension: Mapped[float] = mapped_column(sa.Float, default=20.0)
    tension_history: Mapped[list[float]] = mapped_column(JSONType, default=list)
    world_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class LocationORM(Base):
    __tablename__ = "locations"
    __table_args__ = (
        sa.UniqueConstraint("world_id", "key", name="uq_location_world_key"),
        sa.Index("idx_locations_parent", "parent_id"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("worlds.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    key: Mapped[str] = mapped_column(sa.String(120))
    name: Mapped[str] = mapped_column(sa.String(200))
    location_type: Mapped[str] = mapped_column(sa.String(60), default="wilderness")
    description: Mapped[str] = mapped_column(sa.Text, default="")
    coordinates: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    danger_level: Mapped[int] = mapped_column(sa.Integer, default=0)
    spirit_density: Mapped[float] = mapped_column(sa.Float, default=1.0)
    faction_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    accessible: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    travel_minutes: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    location_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class FactionORM(Base):
    __tablename__ = "factions"
    __table_args__ = (sa.UniqueConstraint("world_id", "key", name="uq_faction_world_key"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("worlds.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(sa.String(120))
    name: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str] = mapped_column(sa.Text, default="")
    faction_type: Mapped[str] = mapped_column(sa.String(60), default="sect")
    headquarters_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    resources: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    member_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    territory: Mapped[list[str]] = mapped_column(JSONType, default=list)
    military_power: Mapped[float] = mapped_column(sa.Float, default=0.0)
    reputation: Mapped[float] = mapped_column(sa.Float, default=0.0)
    leader_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    alliances: Mapped[list[str]] = mapped_column(JSONType, default=list)
    enemies: Mapped[list[str]] = mapped_column(JSONType, default=list)
    goals: Mapped[list[str]] = mapped_column(JSONType, default=list)
    internal_conflicts: Mapped[list[str]] = mapped_column(JSONType, default=list)
    faction_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class CharacterORM(TimestampMixin, Base):
    __tablename__ = "characters"
    __table_args__ = (
        sa.UniqueConstraint("world_id", "key", name="uq_character_world_key"),
        sa.Index("idx_characters_world_location", "world_id", "location_id", "alive"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("worlds.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(sa.String(120))
    name: Mapped[str] = mapped_column(sa.String(200))
    title: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    character_type: Mapped[str] = mapped_column(sa.String(40), default="BACKGROUND", index=True)
    age: Mapped[int] = mapped_column(sa.Integer, default=20)
    gender: Mapped[str] = mapped_column(sa.String(40), default="unspecified")
    location_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    location_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    faction_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    faction_rank: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)

    realm: Mapped[str] = mapped_column(sa.String(60), default="mortal")
    realm_stage: Mapped[str] = mapped_column(sa.String(60), default="normal")
    cultivation_progress: Mapped[float] = mapped_column(sa.Float, default=0.0)
    cultivation_speed: Mapped[float] = mapped_column(sa.Float, default=1.0)
    spiritual_root: Mapped[str] = mapped_column(sa.String(60), default="")
    bottleneck: Mapped[float] = mapped_column(sa.Float, default=0.0)
    mental_state: Mapped[float] = mapped_column(sa.Float, default=0.5)
    foundation_quality: Mapped[float] = mapped_column(sa.Float, default=0.5)

    health: Mapped[int] = mapped_column(sa.Integer, default=100)
    max_health: Mapped[int] = mapped_column(sa.Integer, default=100)
    spiritual_power: Mapped[int] = mapped_column(sa.Integer, default=0)
    max_spiritual_power: Mapped[int] = mapped_column(sa.Integer, default=0)

    strength: Mapped[int] = mapped_column(sa.Integer, default=10)
    agility: Mapped[int] = mapped_column(sa.Integer, default=10)
    perception: Mapped[int] = mapped_column(sa.Integer, default=10)
    intelligence: Mapped[int] = mapped_column(sa.Integer, default=10)
    willpower: Mapped[int] = mapped_column(sa.Integer, default=10)
    charisma: Mapped[int] = mapped_column(sa.Integer, default=10)

    personality: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    background: Mapped[str] = mapped_column(sa.Text, default="")
    long_term_goal: Mapped[str] = mapped_column(sa.Text, default="")
    short_term_goals: Mapped[list[str]] = mapped_column(JSONType, default=list)
    goal_lifecycle: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    current_emotion: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    injuries: Mapped[float] = mapped_column(sa.Float, default=0.0)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    reputation: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    alive: Mapped[bool] = mapped_column(sa.Boolean, default=True, index=True)
    death_event_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    capabilities: Mapped[list[str]] = mapped_column(JSONType, default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    resources: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    progressions: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    character_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class RelationshipORM(Base):
    __tablename__ = "relationships"
    __table_args__ = (
        sa.UniqueConstraint("character_a_id", "character_b_id", name="uq_relationship_pair"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    character_a_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    character_b_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    affection: Mapped[int] = mapped_column(sa.Integer, default=0)
    trust: Mapped[int] = mapped_column(sa.Integer, default=0)
    respect: Mapped[int] = mapped_column(sa.Integer, default=0)
    fear: Mapped[int] = mapped_column(sa.Integer, default=0)
    hatred: Mapped[int] = mapped_column(sa.Integer, default=0)
    suspicion: Mapped[int] = mapped_column(sa.Integer, default=0)
    dependency: Mapped[int] = mapped_column(sa.Integer, default=0)
    familiarity: Mapped[int] = mapped_column(sa.Integer, default=0)
    boundaries: Mapped[int] = mapped_column(sa.Integer, default=50)
    last_interaction_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    interaction_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)


class RelationshipChangeORM(Base):
    """Audit trail: why a relationship moved (Prompt section 14)."""

    __tablename__ = "relationship_changes"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    character_a_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    character_b_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    dimension: Mapped[str] = mapped_column(sa.String(40))
    before: Mapped[int] = mapped_column(sa.Integer)
    after: Mapped[int] = mapped_column(sa.Integer)
    delta: Mapped[int] = mapped_column(sa.Integer)
    reason: Mapped[str] = mapped_column(sa.Text, default="")
    event_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    clamped: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    world_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)


class FactORM(Base):
    __tablename__ = "facts"
    __table_args__ = (sa.UniqueConstraint("world_id", "key", name="uq_fact_world_key"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    key: Mapped[str] = mapped_column(sa.String(160))
    statement: Mapped[str] = mapped_column(sa.Text)
    truth_value: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    scope: Mapped[str] = mapped_column(sa.String(40), default="WORLD")
    sensitivity: Mapped[float] = mapped_column(sa.Float, default=0.0)
    subject_character_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    related_characters: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_at_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    source_event_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)


class CharacterKnowledgeORM(Base):
    """The firewall table: what each character actually believes."""

    __tablename__ = "character_knowledge"
    __table_args__ = (
        sa.UniqueConstraint("character_id", "fact_id", name="uq_knowledge_char_fact"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    character_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    fact_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    knowledge_state: Mapped[str] = mapped_column(sa.String(40), default="UNKNOWN", index=True)
    confidence: Mapped[float] = mapped_column(sa.Float, default=0.0)
    source: Mapped[str] = mapped_column(sa.String(40), default="SEED")
    source_character_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    learned_at_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    notes: Mapped[str] = mapped_column(sa.Text, default="")


class MemoryORM(Base):
    __tablename__ = "memories"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_character_id",
            "related_event_id",
            name="uq_memory_owner_event",
        ),
        sa.Index("idx_memories_owner_importance", "owner_character_id", "importance"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    owner_character_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    memory_type: Mapped[str] = mapped_column(sa.String(40), default="EPISODIC", index=True)
    memory_tag: Mapped[str] = mapped_column(sa.String(40), default="other")
    summary: Mapped[str] = mapped_column(sa.Text)
    importance: Mapped[float] = mapped_column(sa.Float, default=0.5)
    emotional_valence: Mapped[float] = mapped_column(sa.Float, default=0.0)
    related_characters: Mapped[list[str]] = mapped_column(JSONType, default=list)
    related_event_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    related_location_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    created_at_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    last_recalled_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    recall_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    decay: Mapped[float] = mapped_column(sa.Float, default=1.0)
    #: On PostgreSQL this is migrated to vector(N) with an ivfflat index; the
    #: JSON form keeps SQLite working unchanged (DECISIONS D-001).
    embedding: Mapped[list[float] | None] = mapped_column(JSONType, nullable=True)


class ItemORM(Base):
    __tablename__ = "items"
    __table_args__ = (sa.UniqueConstraint("world_id", "key", name="uq_item_world_key"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    key: Mapped[str] = mapped_column(sa.String(120))
    name: Mapped[str] = mapped_column(sa.String(200))
    item_type: Mapped[str] = mapped_column(sa.String(60), default="misc")
    rarity: Mapped[str] = mapped_column(sa.String(60), default="common")
    description: Mapped[str] = mapped_column(sa.Text, default="")
    effects: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    value: Mapped[int] = mapped_column(sa.Integer, default=0)
    stackable: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    item_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class InventoryItemORM(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        sa.UniqueConstraint("character_id", "item_key", name="uq_inventory_char_item"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    character_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    item_key: Mapped[str] = mapped_column(sa.String(120), index=True)
    quantity: Mapped[int] = mapped_column(sa.Integer, default=1)
    equipped: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    bound: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    acquired_at_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)


class SkillORM(Base):
    __tablename__ = "skills"
    __table_args__ = (sa.UniqueConstraint("world_id", "key", name="uq_skill_world_key"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    key: Mapped[str] = mapped_column(sa.String(120))
    name: Mapped[str] = mapped_column(sa.String(200))
    category: Mapped[str] = mapped_column(sa.String(60), default="attack")
    required_realm: Mapped[str] = mapped_column(sa.String(60), default="mortal")
    required_stage: Mapped[str] = mapped_column(sa.String(60), default="normal")
    spiritual_cost: Mapped[int] = mapped_column(sa.Integer, default=0)
    cooldown_minutes: Mapped[int] = mapped_column(sa.Integer, default=0)
    power: Mapped[float] = mapped_column(sa.Float, default=0.0)
    description: Mapped[str] = mapped_column(sa.Text, default="")
    effects: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class CharacterSkillORM(Base):
    __tablename__ = "character_skills"
    __table_args__ = (
        sa.UniqueConstraint("character_id", "skill_key", name="uq_char_skill"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    character_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    skill_key: Mapped[str] = mapped_column(sa.String(120), index=True)
    mastery: Mapped[float] = mapped_column(sa.Float, default=0.1)
    learned_at_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    last_used_minute: Mapped[int] = mapped_column(sa.BigInteger, default=-1_000_000_000)


class QuestORM(Base):
    __tablename__ = "quests"
    __table_args__ = (sa.UniqueConstraint("world_id", "key", name="uq_quest_world_key"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    key: Mapped[str] = mapped_column(sa.String(120))
    name: Mapped[str] = mapped_column(sa.String(200))
    giver_character_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    assignee_character_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(40), default="offered", index=True)
    goal: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    participants: Mapped[list[str]] = mapped_column(JSONType, default=list)
    rewards: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    failure_conditions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    expires_at_minute: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    world_consequences: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    plot_thread_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)


class EventORM(Base):
    """Append-only. The repository exposes no update or delete (Prompt section 17)."""

    __tablename__ = "events"
    __table_args__ = (
        sa.Index("idx_events_world_minute", "world_id", "world_minute"),
        sa.Index("idx_events_actor", "actor_id", "world_minute"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    turn_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(sa.String(60), index=True)
    actor_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    target_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    location_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    before: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    after: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    causes: Mapped[list[str]] = mapped_column(JSONType, default=list)
    cause_event_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    world_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0, index=True)
    rng_seed: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    importance: Mapped[float] = mapped_column(sa.Float, default=0.1)
    visibility: Mapped[str] = mapped_column(sa.String(40), default="LOCAL")
    witnesses: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class DirectorEventORM(TimestampMixin, Base):
    __tablename__ = "director_events"
    __table_args__ = (
        sa.UniqueConstraint("world_id", "dedup_key", name="uq_director_event_world_dedup"),
        sa.Index("idx_director_events_due", "world_id", "status", "scheduled_for_minute"),
        sa.Index("idx_director_events_session_turn", "session_id", "created_turn_number"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    session_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    created_turn_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    created_turn_number: Mapped[int] = mapped_column(sa.Integer)
    dedup_key: Mapped[str] = mapped_column(sa.String(64))
    decision_type: Mapped[str] = mapped_column(sa.String(40))
    event_type: Mapped[str] = mapped_column(sa.String(120))
    status: Mapped[str] = mapped_column(sa.String(40), index=True)
    source_plot_thread_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    source_plot_thread_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    source_plot_thread_stage: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    participant_keys: Mapped[list[str]] = mapped_column(JSONType, default=list)
    participant_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    location_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    proposal: Mapped[str] = mapped_column(sa.Text, default="")
    causal_basis: Mapped[list[str]] = mapped_column(JSONType, default=list)
    narrative_purpose: Mapped[list[str]] = mapped_column(JSONType, default=list)
    urgency: Mapped[str] = mapped_column(sa.String(40), default="low")
    tension_delta: Mapped[float] = mapped_column(sa.Float, default=0.0)
    proposed_at_minute: Mapped[int] = mapped_column(sa.BigInteger)
    scheduled_for_minute: Mapped[int] = mapped_column(sa.BigInteger, index=True)
    activated_at_minute: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    resolved_at_minute: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    cancelled_at_minute: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    canonical_event_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    cancellation_reason: Mapped[str] = mapped_column(sa.Text, default="")
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)


class PlotThreadORM(Base):
    __tablename__ = "plot_threads"
    __table_args__ = (sa.UniqueConstraint("world_id", "key", name="uq_thread_world_key"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    key: Mapped[str] = mapped_column(sa.String(120))
    name: Mapped[str] = mapped_column(sa.String(200))
    status: Mapped[str] = mapped_column(sa.String(40), default="active", index=True)
    importance: Mapped[float] = mapped_column(sa.Float, default=0.5)
    stage: Mapped[int] = mapped_column(sa.Integer, default=0)
    participants: Mapped[list[str]] = mapped_column(JSONType, default=list)
    unresolved_questions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    foreshadowing: Mapped[list[str]] = mapped_column(JSONType, default=list)
    related_facts: Mapped[list[str]] = mapped_column(JSONType, default=list)
    last_advanced_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    next_beat_hint: Mapped[str] = mapped_column(sa.Text, default="")
    escalation_pressure: Mapped[float] = mapped_column(sa.Float, default=0.1)
    thread_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class StoryClockORM(Base):
    __tablename__ = "story_clocks"
    __table_args__ = (sa.UniqueConstraint("world_id", "key", name="uq_clock_world_key"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    key: Mapped[str] = mapped_column(sa.String(120))
    name: Mapped[str] = mapped_column(sa.String(200))
    kind: Mapped[str] = mapped_column(sa.String(20), default="danger")
    status: Mapped[str] = mapped_column(sa.String(20), default="running", index=True)
    segments: Mapped[int] = mapped_column(sa.Integer, default=4)
    filled: Mapped[int] = mapped_column(sa.Integer, default=0)
    minutes_per_segment: Mapped[int] = mapped_column(sa.Integer, default=0)
    started_at_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    thread_key: Mapped[str] = mapped_column(sa.String(120), default="")
    visible: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    consequence: Mapped[str] = mapped_column(sa.Text, default="")
    clock_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class GameSessionORM(TimestampMixin, Base):
    __tablename__ = "game_sessions"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    player_character_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    session_seed: Mapped[str] = mapped_column(sa.String(120), default="session")
    status: Mapped[str] = mapped_column(sa.String(40), default="active")
    turn_number: Mapped[int] = mapped_column(sa.Integer, default=0)
    playthrough_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)


class TurnORM(Base):
    __tablename__ = "turns"
    __table_args__ = (
        sa.UniqueConstraint("session_id", "turn_number", name="uq_turn_session_number"),
        sa.Index("idx_turns_idem", "idempotency_key", unique=True),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    turn_number: Mapped[int] = mapped_column(sa.Integer, default=0)
    player_input: Mapped[str] = mapped_column(sa.Text, default="")
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(40), default="CANONICAL_COMMITTED", index=True
    )
    world_minute_before: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    world_minute_after: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    canonical_payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    last_error: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class TurnTraceORM(Base):
    __tablename__ = "turn_traces"

    turn_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(sa.String(64), default="")
    session_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class NarrativeSegmentORM(Base):
    __tablename__ = "narrative_segments"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    turn_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    kind: Mapped[str] = mapped_column(sa.String(40), default="scene")
    text: Mapped[str] = mapped_column(sa.Text, default="")
    world_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class SaveSlotORM(Base):
    """A restore point: the entire world and story, frozen.

    Rewinding by reversing state changes would mean unwinding an append-only
    event log, memories, and prose - so a save is simply a complete copy of
    every row belonging to the session. This world is small enough that the
    honest approach is also the cheap one.
    """

    __tablename__ = "save_slots"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    playthrough_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    session_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    world_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    name: Mapped[str] = mapped_column(sa.String(80), default="")
    #: Shown in the save list so the player can tell their saves apart.
    player_name: Mapped[str] = mapped_column(sa.String(80), default="")
    turn_number: Mapped[int] = mapped_column(sa.Integer, default=0)
    world_minute: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    time_label: Mapped[str] = mapped_column(sa.String(120), default="")
    location_name: Mapped[str] = mapped_column(sa.String(120), default="")
    excerpt: Mapped[str] = mapped_column(sa.Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)

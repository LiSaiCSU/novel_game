"""ORM row <-> domain model translation.

The engine never sees an ORM object, and the ORM never sees engine logic. This
module is the only place the two vocabularies meet.
"""

from __future__ import annotations

from typing import Any

from database.models.orm import (
    CharacterKnowledgeORM,
    CharacterORM,
    CharacterSkillORM,
    EventORM,
    FactionORM,
    FactORM,
    GameSessionORM,
    InventoryItemORM,
    ItemORM,
    LocationORM,
    MemoryORM,
    NarrativeSegmentORM,
    PlotThreadORM,
    QuestORM,
    RelationshipChangeORM,
    RelationshipORM,
    SkillORM,
    WorldORM,
)
from engine.core.models import (
    Character,
    CharacterKnowledge,
    CharacterSkill,
    Emotion,
    Event,
    Fact,
    Faction,
    GameSession,
    InventoryItem,
    Item,
    Location,
    Memory,
    NarrativeSegment,
    Personality,
    PlotThread,
    Quest,
    Relationship,
    RelationshipChange,
    Reputation,
    Schedule,
    Skill,
    World,
)
from engine.core.types import (
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


# --- world -----------------------------------------------------------------
def world_to_domain(row: WorldORM) -> World:
    return World(
        id=row.id,
        name=row.name,
        description=row.description,
        current_minute=row.current_minute,
        calendar_config=row.calendar_config or {},
        world_seed=row.world_seed,
        content_pack=row.content_pack,
        rule_version=row.rule_version,
        narrative_tension=row.narrative_tension,
        tension_history=list(row.tension_history or []),
        metadata=row.world_metadata or {},
    )


def world_to_orm(model: World) -> WorldORM:
    return WorldORM(
        id=model.id,
        name=model.name,
        description=model.description,
        current_minute=model.current_minute,
        calendar_config=model.calendar_config,
        world_seed=model.world_seed,
        content_pack=model.content_pack,
        rule_version=model.rule_version,
        narrative_tension=model.narrative_tension,
        tension_history=model.tension_history,
        world_metadata=model.metadata,
    )


# --- location / faction -----------------------------------------------------
def location_to_domain(row: LocationORM) -> Location:
    return Location(
        id=row.id,
        world_id=row.world_id,
        parent_id=row.parent_id,
        key=row.key,
        name=row.name,
        location_type=row.location_type,
        description=row.description,
        coordinates=row.coordinates or {},
        danger_level=row.danger_level,
        spirit_density=row.spirit_density,
        faction_key=row.faction_key,
        accessible=row.accessible,
        travel_minutes=row.travel_minutes or {},
        metadata=row.location_metadata or {},
    )


def location_to_orm(model: Location) -> LocationORM:
    return LocationORM(
        id=model.id,
        world_id=model.world_id,
        parent_id=model.parent_id,
        key=model.key,
        name=model.name,
        location_type=model.location_type,
        description=model.description,
        coordinates=model.coordinates,
        danger_level=model.danger_level,
        spirit_density=model.spirit_density,
        faction_key=model.faction_key,
        accessible=model.accessible,
        travel_minutes=model.travel_minutes,
        location_metadata=model.metadata,
    )


def faction_to_domain(row: FactionORM) -> Faction:
    return Faction(
        id=row.id,
        world_id=row.world_id,
        key=row.key,
        name=row.name,
        description=row.description,
        faction_type=row.faction_type,
        headquarters_key=row.headquarters_key,
        resources=row.resources or {},
        member_count=row.member_count,
        territory=list(row.territory or []),
        military_power=row.military_power,
        reputation=row.reputation,
        leader_key=row.leader_key,
        alliances=list(row.alliances or []),
        enemies=list(row.enemies or []),
        goals=list(row.goals or []),
        internal_conflicts=list(row.internal_conflicts or []),
        metadata=row.faction_metadata or {},
    )


def faction_to_orm(model: Faction) -> FactionORM:
    return FactionORM(
        id=model.id,
        world_id=model.world_id,
        key=model.key,
        name=model.name,
        description=model.description,
        faction_type=model.faction_type,
        headquarters_key=model.headquarters_key,
        resources=model.resources,
        member_count=model.member_count,
        territory=model.territory,
        military_power=model.military_power,
        reputation=model.reputation,
        leader_key=model.leader_key,
        alliances=model.alliances,
        enemies=model.enemies,
        goals=model.goals,
        internal_conflicts=model.internal_conflicts,
        faction_metadata=model.metadata,
    )


# --- character --------------------------------------------------------------
_CHARACTER_SCALARS = (
    "key",
    "name",
    "title",
    "age",
    "gender",
    "location_id",
    "location_key",
    "faction_key",
    "faction_rank",
    "realm",
    "realm_stage",
    "cultivation_progress",
    "cultivation_speed",
    "spiritual_root",
    "bottleneck",
    "mental_state",
    "foundation_quality",
    "health",
    "max_health",
    "spiritual_power",
    "max_spiritual_power",
    "strength",
    "agility",
    "perception",
    "intelligence",
    "willpower",
    "charisma",
    "background",
    "long_term_goal",
    "injuries",
    "alive",
    "death_event_id",
)


def character_to_domain(row: CharacterORM) -> Character:
    data: dict[str, Any] = {name: getattr(row, name) for name in _CHARACTER_SCALARS}
    return Character(
        id=row.id,
        world_id=row.world_id,
        character_type=CharacterType(row.character_type),
        personality=Personality(**(row.personality or {})),
        short_term_goals=list(row.short_term_goals or []),
        current_emotion=Emotion(**(row.current_emotion or {})),
        schedule=Schedule(**(row.schedule or {})),
        reputation=Reputation(**(row.reputation or {})),
        capabilities=list(row.capabilities or []),
        metadata=row.character_metadata or {},
        **data,
    )


def character_to_orm(model: Character) -> CharacterORM:
    data: dict[str, Any] = {name: getattr(model, name) for name in _CHARACTER_SCALARS}
    return CharacterORM(
        id=model.id,
        world_id=model.world_id,
        character_type=str(model.character_type),
        personality=model.personality.model_dump(),
        short_term_goals=model.short_term_goals,
        current_emotion=model.current_emotion.model_dump(),
        schedule=model.schedule.model_dump(mode="json"),
        reputation=model.reputation.model_dump(),
        capabilities=model.capabilities,
        character_metadata=model.metadata,
        **data,
    )


# --- relationships ----------------------------------------------------------
_RELATIONSHIP_FIELDS = (
    "world_id",
    "character_a_id",
    "character_b_id",
    "affection",
    "trust",
    "respect",
    "fear",
    "hatred",
    "suspicion",
    "dependency",
    "familiarity",
    "last_interaction_minute",
    "interaction_count",
)


def relationship_to_domain(row: RelationshipORM) -> Relationship:
    return Relationship(
        id=row.id,
        tags=list(row.tags or []),
        **{name: getattr(row, name) for name in _RELATIONSHIP_FIELDS},
    )


def relationship_to_orm(model: Relationship) -> RelationshipORM:
    return RelationshipORM(
        id=model.id,
        tags=model.tags,
        **{name: getattr(model, name) for name in _RELATIONSHIP_FIELDS},
    )


def relationship_change_to_orm(model: RelationshipChange) -> RelationshipChangeORM:
    return RelationshipChangeORM(**model.model_dump())


def relationship_change_to_domain(row: RelationshipChangeORM) -> RelationshipChange:
    return RelationshipChange(
        id=row.id,
        world_id=row.world_id,
        character_a_id=row.character_a_id,
        character_b_id=row.character_b_id,
        dimension=row.dimension,
        before=row.before,
        after=row.after,
        delta=row.delta,
        reason=row.reason,
        event_id=row.event_id,
        clamped=row.clamped,
        world_minute=row.world_minute,
    )


# --- knowledge --------------------------------------------------------------
def fact_to_domain(row: FactORM) -> Fact:
    return Fact(
        id=row.id,
        world_id=row.world_id,
        key=row.key,
        statement=row.statement,
        truth_value=row.truth_value,
        scope=FactScope(row.scope),
        sensitivity=row.sensitivity,
        subject_character_key=row.subject_character_key,
        related_characters=list(row.related_characters or []),
        created_at_minute=row.created_at_minute,
        source_event_id=row.source_event_id,
    )


def fact_to_orm(model: Fact) -> FactORM:
    return FactORM(
        id=model.id,
        world_id=model.world_id,
        key=model.key,
        statement=model.statement,
        truth_value=model.truth_value,
        scope=str(model.scope),
        sensitivity=model.sensitivity,
        subject_character_key=model.subject_character_key,
        related_characters=model.related_characters,
        created_at_minute=model.created_at_minute,
        source_event_id=model.source_event_id,
    )


def knowledge_to_domain(row: CharacterKnowledgeORM) -> CharacterKnowledge:
    return CharacterKnowledge(
        id=row.id,
        character_id=row.character_id,
        fact_id=row.fact_id,
        knowledge_state=KnowledgeState(row.knowledge_state),
        confidence=row.confidence,
        source=KnowledgeSource(row.source),
        source_character_id=row.source_character_id,
        learned_at_minute=row.learned_at_minute,
        notes=row.notes,
    )


def knowledge_to_orm(model: CharacterKnowledge) -> CharacterKnowledgeORM:
    return CharacterKnowledgeORM(
        id=model.id,
        character_id=model.character_id,
        fact_id=model.fact_id,
        knowledge_state=str(model.knowledge_state),
        confidence=model.confidence,
        source=str(model.source),
        source_character_id=model.source_character_id,
        learned_at_minute=model.learned_at_minute,
        notes=model.notes,
    )


# --- memory -----------------------------------------------------------------
def memory_to_domain(row: MemoryORM) -> Memory:
    return Memory(
        id=row.id,
        world_id=row.world_id,
        owner_character_id=row.owner_character_id,
        memory_type=MemoryType(row.memory_type),
        memory_tag=MemoryTag(row.memory_tag),
        summary=row.summary,
        importance=row.importance,
        emotional_valence=row.emotional_valence,
        related_characters=list(row.related_characters or []),
        related_event_id=row.related_event_id,
        related_location_id=row.related_location_id,
        created_at_minute=row.created_at_minute,
        last_recalled_minute=row.last_recalled_minute,
        recall_count=row.recall_count,
        decay=row.decay,
        embedding=list(row.embedding) if row.embedding else None,
    )


def memory_to_orm(model: Memory) -> MemoryORM:
    return MemoryORM(
        id=model.id,
        world_id=model.world_id,
        owner_character_id=model.owner_character_id,
        memory_type=str(model.memory_type),
        memory_tag=str(model.memory_tag),
        summary=model.summary,
        importance=model.importance,
        emotional_valence=model.emotional_valence,
        related_characters=model.related_characters,
        related_event_id=model.related_event_id,
        related_location_id=model.related_location_id,
        created_at_minute=model.created_at_minute,
        last_recalled_minute=model.last_recalled_minute,
        recall_count=model.recall_count,
        decay=model.decay,
        embedding=model.embedding,
    )


# --- items and skills -------------------------------------------------------
def item_to_domain(row: ItemORM) -> Item:
    return Item(
        id=row.id,
        world_id=row.world_id,
        key=row.key,
        name=row.name,
        item_type=row.item_type,
        rarity=row.rarity,
        description=row.description,
        effects=row.effects or {},
        value=row.value,
        stackable=row.stackable,
        metadata=row.item_metadata or {},
    )


def item_to_orm(model: Item) -> ItemORM:
    return ItemORM(
        id=model.id,
        world_id=model.world_id,
        key=model.key,
        name=model.name,
        item_type=model.item_type,
        rarity=model.rarity,
        description=model.description,
        effects=model.effects,
        value=model.value,
        stackable=model.stackable,
        item_metadata=model.metadata,
    )


def inventory_to_domain(row: InventoryItemORM) -> InventoryItem:
    return InventoryItem(
        id=row.id,
        character_id=row.character_id,
        item_key=row.item_key,
        quantity=row.quantity,
        equipped=row.equipped,
        bound=row.bound,
        acquired_at_minute=row.acquired_at_minute,
    )


def inventory_to_orm(model: InventoryItem) -> InventoryItemORM:
    return InventoryItemORM(**model.model_dump())


def skill_to_domain(row: SkillORM) -> Skill:
    return Skill(
        id=row.id,
        world_id=row.world_id,
        key=row.key,
        name=row.name,
        category=row.category,
        required_realm=row.required_realm,
        required_stage=row.required_stage,
        spiritual_cost=row.spiritual_cost,
        cooldown_minutes=row.cooldown_minutes,
        power=row.power,
        description=row.description,
        effects=row.effects or {},
    )


def skill_to_orm(model: Skill) -> SkillORM:
    return SkillORM(**model.model_dump())


def character_skill_to_domain(row: CharacterSkillORM) -> CharacterSkill:
    return CharacterSkill(
        id=row.id,
        character_id=row.character_id,
        skill_key=row.skill_key,
        mastery=row.mastery,
        learned_at_minute=row.learned_at_minute,
        last_used_minute=row.last_used_minute,
    )


def character_skill_to_orm(model: CharacterSkill) -> CharacterSkillORM:
    return CharacterSkillORM(**model.model_dump())


# --- quests / events / threads ----------------------------------------------
def quest_to_domain(row: QuestORM) -> Quest:
    return Quest(
        id=row.id,
        world_id=row.world_id,
        key=row.key,
        name=row.name,
        giver_character_key=row.giver_character_key,
        assignee_character_key=row.assignee_character_key,
        status=QuestStatus(row.status),
        goal=row.goal or {},
        constraints=row.constraints or {},
        participants=list(row.participants or []),
        rewards=row.rewards or {},
        failure_conditions=list(row.failure_conditions or []),
        expires_at_minute=row.expires_at_minute,
        world_consequences=row.world_consequences or {},
        plot_thread_key=row.plot_thread_key,
    )


def quest_to_orm(model: Quest) -> QuestORM:
    data = model.model_dump(mode="json")
    data["status"] = str(model.status)
    return QuestORM(**data)


def event_to_domain(row: EventORM) -> Event:
    return Event(
        id=row.id,
        world_id=row.world_id,
        turn_id=row.turn_id,
        event_type=row.event_type,
        actor_id=row.actor_id,
        target_ids=list(row.target_ids or []),
        location_id=row.location_id,
        before=row.before or {},
        after=row.after or {},
        causes=list(row.causes or []),
        cause_event_ids=list(row.cause_event_ids or []),
        payload=row.payload or {},
        world_minute=row.world_minute,
        rng_seed=row.rng_seed,
        importance=row.importance,
        visibility=Visibility(row.visibility),
        witnesses=list(row.witnesses or []),
    )


def event_to_orm(model: Event) -> EventORM:
    data = model.model_dump(mode="json")
    data["visibility"] = str(model.visibility)
    return EventORM(**data)


def thread_to_domain(row: PlotThreadORM) -> PlotThread:
    return PlotThread(
        id=row.id,
        world_id=row.world_id,
        key=row.key,
        name=row.name,
        status=ThreadStatus(row.status),
        importance=row.importance,
        stage=row.stage,
        participants=list(row.participants or []),
        unresolved_questions=list(row.unresolved_questions or []),
        foreshadowing=list(row.foreshadowing or []),
        related_facts=list(row.related_facts or []),
        last_advanced_minute=row.last_advanced_minute,
        next_beat_hint=row.next_beat_hint,
        escalation_pressure=row.escalation_pressure,
        metadata=row.thread_metadata or {},
    )


def thread_to_orm(model: PlotThread) -> PlotThreadORM:
    return PlotThreadORM(
        id=model.id,
        world_id=model.world_id,
        key=model.key,
        name=model.name,
        status=str(model.status),
        importance=model.importance,
        stage=model.stage,
        participants=model.participants,
        unresolved_questions=model.unresolved_questions,
        foreshadowing=model.foreshadowing,
        related_facts=model.related_facts,
        last_advanced_minute=model.last_advanced_minute,
        next_beat_hint=model.next_beat_hint,
        escalation_pressure=model.escalation_pressure,
        thread_metadata=model.metadata,
    )


# --- sessions ---------------------------------------------------------------
def session_to_domain(row: GameSessionORM) -> GameSession:
    return GameSession(
        id=row.id,
        world_id=row.world_id,
        player_character_id=row.player_character_id,
        session_seed=row.session_seed,
        status=row.status,
        turn_number=row.turn_number,
    )


def session_to_orm(model: GameSession) -> GameSessionORM:
    return GameSessionORM(**model.model_dump())


def narrative_to_domain(row: NarrativeSegmentORM) -> NarrativeSegment:
    return NarrativeSegment(
        id=row.id,
        session_id=row.session_id,
        turn_id=row.turn_id,
        kind=row.kind,
        text=row.text,
        world_minute=row.world_minute,
    )


def narrative_to_orm(model: NarrativeSegment) -> NarrativeSegmentORM:
    return NarrativeSegmentORM(**model.model_dump())

"""SQLAlchemy adapters for the engine's repository ports.

Reads return domain models; writes go exclusively through
:meth:`SqlUnitOfWork.apply`, which mirrors the in-memory adapter's semantics so
both backends behave identically from the engine's point of view.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from database import mappers as m
from database.models.orm import (
    CharacterKnowledgeORM,
    CharacterORM,
    CharacterSkillORM,
    DirectorEventORM,
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
    TurnORM,
    TurnTraceORM,
    WorldORM,
)
from database.repositories.state_snapshot import SqlWorldStateRepository
from engine.core.errors import EngineError
from engine.core.ids import new_id
from engine.core.models import (
    Character,
    CharacterKnowledge,
    CharacterSkill,
    DirectorEvent,
    Event,
    Fact,
    Faction,
    GameSession,
    InventoryItem,
    Item,
    Location,
    Memory,
    NarrativeSegment,
    PlotThread,
    Quest,
    Relationship,
    RelationshipChange,
    Skill,
    World,
)
from engine.core.mutations import ChangeKind, ChangeSet
from engine.core.types import KnowledgeState


class _Repo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def _scalars(self, stmt):
        return (await self.s.execute(stmt)).scalars().all()

    async def _one(self, stmt):
        return (await self.s.execute(stmt)).scalars().first()


class SqlWorldRepo(_Repo):
    async def get(self, world_id: str) -> World | None:
        row = await self.s.get(WorldORM, world_id)
        return m.world_to_domain(row) if row else None

    async def save(self, world: World) -> None:
        row = await self.s.get(WorldORM, world.id)
        if row is None:
            self.s.add(m.world_to_orm(world))
            return
        for field, value in m.world_to_orm(world).__dict__.items():
            if field.startswith("_") or field == "id":
                continue
            setattr(row, field, value)

    async def list_all(self) -> list[World]:
        return [m.world_to_domain(r) for r in await self._scalars(sa.select(WorldORM))]


class SqlLocationRepo(_Repo):
    async def get(self, location_id: str) -> Location | None:
        row = await self.s.get(LocationORM, location_id)
        return m.location_to_domain(row) if row else None

    async def get_by_key(self, world_id: str, key: str) -> Location | None:
        row = await self._one(
            sa.select(LocationORM).where(LocationORM.world_id == world_id, LocationORM.key == key)
        )
        return m.location_to_domain(row) if row else None

    async def list_for_world(self, world_id: str) -> list[Location]:
        rows = await self._scalars(sa.select(LocationORM).where(LocationORM.world_id == world_id))
        return [m.location_to_domain(r) for r in rows]

    async def children(self, location_id: str) -> list[Location]:
        rows = await self._scalars(
            sa.select(LocationORM).where(LocationORM.parent_id == location_id)
        )
        return [m.location_to_domain(r) for r in rows]


class SqlFactionRepo(_Repo):
    async def get(self, faction_id: str) -> Faction | None:
        row = await self.s.get(FactionORM, faction_id)
        return m.faction_to_domain(row) if row else None

    async def get_by_key(self, world_id: str, key: str) -> Faction | None:
        row = await self._one(
            sa.select(FactionORM).where(FactionORM.world_id == world_id, FactionORM.key == key)
        )
        return m.faction_to_domain(row) if row else None

    async def list_for_world(self, world_id: str) -> list[Faction]:
        rows = await self._scalars(sa.select(FactionORM).where(FactionORM.world_id == world_id))
        return [m.faction_to_domain(r) for r in rows]


class SqlCharacterRepo(_Repo):
    async def get(self, character_id: str) -> Character | None:
        row = await self.s.get(CharacterORM, character_id)
        return m.character_to_domain(row) if row else None

    async def get_by_key(self, world_id: str, key: str) -> Character | None:
        row = await self._one(
            sa.select(CharacterORM).where(
                CharacterORM.world_id == world_id, CharacterORM.key == key
            )
        )
        return m.character_to_domain(row) if row else None

    async def list_for_world(self, world_id: str, *, alive_only: bool = True) -> list[Character]:
        stmt = sa.select(CharacterORM).where(CharacterORM.world_id == world_id)
        if alive_only:
            stmt = stmt.where(CharacterORM.alive.is_(True))
        return [m.character_to_domain(r) for r in await self._scalars(stmt)]

    async def list_at_location(
        self, world_id: str, location_id: str, *, alive_only: bool = True
    ) -> list[Character]:
        stmt = sa.select(CharacterORM).where(
            CharacterORM.world_id == world_id, CharacterORM.location_id == location_id
        )
        if alive_only:
            stmt = stmt.where(CharacterORM.alive.is_(True))
        return [m.character_to_domain(r) for r in await self._scalars(stmt)]

    async def list_by_type(self, world_id: str, character_type: str) -> list[Character]:
        stmt = sa.select(CharacterORM).where(
            CharacterORM.world_id == world_id, CharacterORM.character_type == character_type
        )
        return [m.character_to_domain(r) for r in await self._scalars(stmt)]


class SqlRelationshipRepo(_Repo):
    async def get(self, character_a_id: str, character_b_id: str) -> Relationship | None:
        row = await self._one(
            sa.select(RelationshipORM).where(
                RelationshipORM.character_a_id == character_a_id,
                RelationshipORM.character_b_id == character_b_id,
            )
        )
        return m.relationship_to_domain(row) if row else None

    async def list_for_character(self, character_id: str) -> list[Relationship]:
        rows = await self._scalars(
            sa.select(RelationshipORM).where(RelationshipORM.character_a_id == character_id)
        )
        return [m.relationship_to_domain(r) for r in rows]

    async def list_changes(self, character_id: str, limit: int = 50) -> list[RelationshipChange]:
        rows = await self._scalars(
            sa.select(RelationshipChangeORM)
            .where(
                sa.or_(
                    RelationshipChangeORM.character_a_id == character_id,
                    RelationshipChangeORM.character_b_id == character_id,
                )
            )
            .order_by(RelationshipChangeORM.world_minute.desc())
            .limit(limit)
        )
        return [m.relationship_change_to_domain(r) for r in rows]


class SqlKnowledgeRepo(_Repo):
    async def get_fact(self, fact_id: str) -> Fact | None:
        row = await self.s.get(FactORM, fact_id)
        return m.fact_to_domain(row) if row else None

    async def get_fact_by_key(self, world_id: str, key: str) -> Fact | None:
        row = await self._one(
            sa.select(FactORM).where(FactORM.world_id == world_id, FactORM.key == key)
        )
        return m.fact_to_domain(row) if row else None

    async def list_facts(self, world_id: str) -> list[Fact]:
        rows = await self._scalars(sa.select(FactORM).where(FactORM.world_id == world_id))
        return [m.fact_to_domain(r) for r in rows]

    async def get_knowledge(self, character_id: str, fact_id: str) -> CharacterKnowledge | None:
        row = await self._one(
            sa.select(CharacterKnowledgeORM).where(
                CharacterKnowledgeORM.character_id == character_id,
                CharacterKnowledgeORM.fact_id == fact_id,
            )
        )
        return m.knowledge_to_domain(row) if row else None

    async def list_known(self, character_id: str) -> list[tuple[CharacterKnowledge, Fact]]:
        """The god-view firewall, enforced in SQL: UNKNOWN never leaves the database."""
        stmt = (
            sa.select(CharacterKnowledgeORM, FactORM)
            .join(FactORM, FactORM.id == CharacterKnowledgeORM.fact_id)
            .where(
                CharacterKnowledgeORM.character_id == character_id,
                CharacterKnowledgeORM.knowledge_state != str(KnowledgeState.UNKNOWN),
            )
        )
        rows = (await self.s.execute(stmt)).all()
        return [(m.knowledge_to_domain(k), m.fact_to_domain(f)) for k, f in rows]

    async def list_knowers(self, fact_id: str) -> list[CharacterKnowledge]:
        rows = await self._scalars(
            sa.select(CharacterKnowledgeORM).where(
                CharacterKnowledgeORM.fact_id == fact_id,
                CharacterKnowledgeORM.knowledge_state != str(KnowledgeState.UNKNOWN),
            )
        )
        return [m.knowledge_to_domain(r) for r in rows]


class SqlMemoryRepo(_Repo):
    async def list_for_owner(
        self, owner_character_id: str, *, memory_types: list[str] | None = None, limit: int = 200
    ) -> list[Memory]:
        stmt = sa.select(MemoryORM).where(MemoryORM.owner_character_id == owner_character_id)
        if memory_types:
            stmt = stmt.where(MemoryORM.memory_type.in_(memory_types))
        stmt = stmt.order_by(MemoryORM.created_at_minute.desc()).limit(limit)
        return [m.memory_to_domain(r) for r in await self._scalars(stmt)]

    async def get_by_event(self, owner_character_id: str, related_event_id: str) -> Memory | None:
        row = await self._one(
            sa.select(MemoryORM).where(
                MemoryORM.owner_character_id == owner_character_id,
                MemoryORM.related_event_id == related_event_id,
            )
        )
        return m.memory_to_domain(row) if row else None

    async def add(self, memory: Memory) -> None:
        if memory.related_event_id is not None:
            existing = await self.get_by_event(memory.owner_character_id, memory.related_event_id)
            if existing is not None:
                return
        self.s.add(m.memory_to_orm(memory))

    async def touch(self, memory_id: str, at_minute: int) -> None:
        row = await self.s.get(MemoryORM, memory_id)
        if row is not None:
            row.last_recalled_minute = at_minute
            row.recall_count += 1


class SqlItemRepo(_Repo):
    async def get_by_key(self, world_id: str, key: str) -> Item | None:
        row = await self._one(
            sa.select(ItemORM).where(ItemORM.world_id == world_id, ItemORM.key == key)
        )
        return m.item_to_domain(row) if row else None

    async def list_for_world(self, world_id: str) -> list[Item]:
        rows = await self._scalars(sa.select(ItemORM).where(ItemORM.world_id == world_id))
        return [m.item_to_domain(r) for r in rows]

    async def list_inventory(self, character_id: str) -> list[InventoryItem]:
        rows = await self._scalars(
            sa.select(InventoryItemORM).where(InventoryItemORM.character_id == character_id)
        )
        return [m.inventory_to_domain(r) for r in rows]

    async def get_inventory_item(self, character_id: str, item_key: str) -> InventoryItem | None:
        row = await self._one(
            sa.select(InventoryItemORM).where(
                InventoryItemORM.character_id == character_id,
                InventoryItemORM.item_key == item_key,
            )
        )
        return m.inventory_to_domain(row) if row else None


class SqlSkillRepo(_Repo):
    async def get_by_key(self, world_id: str, key: str) -> Skill | None:
        row = await self._one(
            sa.select(SkillORM).where(SkillORM.world_id == world_id, SkillORM.key == key)
        )
        return m.skill_to_domain(row) if row else None

    async def list_for_world(self, world_id: str) -> list[Skill]:
        rows = await self._scalars(sa.select(SkillORM).where(SkillORM.world_id == world_id))
        return [m.skill_to_domain(r) for r in rows]

    async def list_for_character(self, character_id: str) -> list[CharacterSkill]:
        rows = await self._scalars(
            sa.select(CharacterSkillORM).where(CharacterSkillORM.character_id == character_id)
        )
        return [m.character_skill_to_domain(r) for r in rows]

    async def get_for_character(self, character_id: str, skill_key: str) -> CharacterSkill | None:
        row = await self._one(
            sa.select(CharacterSkillORM).where(
                CharacterSkillORM.character_id == character_id,
                CharacterSkillORM.skill_key == skill_key,
            )
        )
        return m.character_skill_to_domain(row) if row else None


class SqlQuestRepo(_Repo):
    async def get(self, quest_id: str) -> Quest | None:
        row = await self.s.get(QuestORM, quest_id)
        return m.quest_to_domain(row) if row else None

    async def get_by_key(self, world_id: str, key: str) -> Quest | None:
        row = await self._one(
            sa.select(QuestORM).where(QuestORM.world_id == world_id, QuestORM.key == key)
        )
        return m.quest_to_domain(row) if row else None

    async def list_for_world(self, world_id: str, *, status: str | None = None) -> list[Quest]:
        stmt = sa.select(QuestORM).where(QuestORM.world_id == world_id)
        if status:
            stmt = stmt.where(QuestORM.status == status)
        return [m.quest_to_domain(r) for r in await self._scalars(stmt)]


class SqlEventRepo(_Repo):
    """Append-only: no update, no delete, by design."""

    async def append(self, event: Event) -> None:
        self.s.add(m.event_to_orm(event))

    async def list_recent(self, world_id: str, limit: int = 20) -> list[Event]:
        rows = await self._scalars(
            sa.select(EventORM)
            .where(EventORM.world_id == world_id)
            .order_by(EventORM.world_minute.desc(), EventORM.created_at.desc())
            .limit(limit)
        )
        return [m.event_to_domain(r) for r in reversed(list(rows))]

    async def list_for_actor(self, actor_id: str, limit: int = 20) -> list[Event]:
        rows = await self._scalars(
            sa.select(EventORM)
            .where(EventORM.actor_id == actor_id)
            .order_by(EventORM.world_minute.desc())
            .limit(limit)
        )
        return [m.event_to_domain(r) for r in reversed(list(rows))]

    async def list_since(self, world_id: str, since_minute: int) -> list[Event]:
        rows = await self._scalars(
            sa.select(EventORM)
            .where(EventORM.world_id == world_id, EventORM.world_minute >= since_minute)
            .order_by(EventORM.world_minute)
        )
        return [m.event_to_domain(r) for r in rows]

    async def get(self, event_id: str) -> Event | None:
        row = await self.s.get(EventORM, event_id)
        return m.event_to_domain(row) if row else None


class SqlPlotThreadRepo(_Repo):
    async def get_by_key(self, world_id: str, key: str) -> PlotThread | None:
        row = await self._one(
            sa.select(PlotThreadORM).where(
                PlotThreadORM.world_id == world_id, PlotThreadORM.key == key
            )
        )
        return m.thread_to_domain(row) if row else None

    async def list_for_world(self, world_id: str, *, status: str | None = None) -> list[PlotThread]:
        stmt = sa.select(PlotThreadORM).where(PlotThreadORM.world_id == world_id)
        if status:
            stmt = stmt.where(PlotThreadORM.status == status)
        return [m.thread_to_domain(r) for r in await self._scalars(stmt)]


class SqlDirectorEventRepo(_Repo):
    async def get(self, director_event_id: str) -> DirectorEvent | None:
        row = await self.s.get(DirectorEventORM, director_event_id)
        return m.director_event_to_domain(row) if row else None

    async def get_by_dedup_key(self, world_id: str, dedup_key: str) -> DirectorEvent | None:
        row = await self._one(
            sa.select(DirectorEventORM).where(
                DirectorEventORM.world_id == world_id,
                DirectorEventORM.dedup_key == dedup_key,
            )
        )
        return m.director_event_to_domain(row) if row else None

    async def list_for_world(
        self, world_id: str, *, status: str | None = None, limit: int = 100
    ) -> list[DirectorEvent]:
        stmt = (
            sa.select(DirectorEventORM)
            .where(DirectorEventORM.world_id == world_id)
            .order_by(DirectorEventORM.created_turn_number.desc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(DirectorEventORM.status == status)
        return [m.director_event_to_domain(row) for row in await self._scalars(stmt)]

    async def list_due(self, world_id: str, through_minute: int) -> list[DirectorEvent]:
        rows = await self._scalars(
            sa.select(DirectorEventORM)
            .where(
                DirectorEventORM.world_id == world_id,
                DirectorEventORM.status == "SCHEDULED",
                DirectorEventORM.scheduled_for_minute <= through_minute,
            )
            .order_by(DirectorEventORM.scheduled_for_minute, DirectorEventORM.id)
        )
        return [m.director_event_to_domain(row) for row in rows]

    async def last_for_session(self, session_id: str) -> DirectorEvent | None:
        row = await self._one(
            sa.select(DirectorEventORM)
            .where(DirectorEventORM.session_id == session_id)
            .order_by(DirectorEventORM.created_turn_number.desc())
            .limit(1)
        )
        return m.director_event_to_domain(row) if row else None

    async def count_resolved_between(
        self, world_id: str, start_minute: int, end_minute: int
    ) -> int:
        value = await self.s.scalar(
            sa.select(sa.func.count())
            .select_from(DirectorEventORM)
            .where(
                DirectorEventORM.world_id == world_id,
                DirectorEventORM.status == "RESOLVED",
                DirectorEventORM.scheduled_for_minute >= start_minute,
                DirectorEventORM.scheduled_for_minute < end_minute,
            )
        )
        return int(value or 0)

    async def count_booked_between(self, world_id: str, start_minute: int, end_minute: int) -> int:
        value = await self.s.scalar(
            sa.select(sa.func.count())
            .select_from(DirectorEventORM)
            .where(
                DirectorEventORM.world_id == world_id,
                DirectorEventORM.status.in_(["SCHEDULED", "ACTIVE", "RESOLVED"]),
                DirectorEventORM.scheduled_for_minute >= start_minute,
                DirectorEventORM.scheduled_for_minute < end_minute,
            )
        )
        return int(value or 0)


class SqlSessionRepo(_Repo):
    async def get(self, session_id: str) -> GameSession | None:
        row = await self.s.get(GameSessionORM, session_id)
        return m.session_to_domain(row) if row else None

    async def save(self, session: GameSession) -> None:
        row = await self.s.get(GameSessionORM, session.id)
        if row is None:
            self.s.add(m.session_to_orm(session))
            return
        row.turn_number = session.turn_number
        row.status = session.status

    async def list_for_world(self, world_id: str) -> list[GameSession]:
        rows = await self._scalars(
            sa.select(GameSessionORM).where(GameSessionORM.world_id == world_id)
        )
        return [m.session_to_domain(r) for r in rows]


class SqlTurnRepo(_Repo):
    async def record(self, turn: dict[str, Any]) -> None:
        turn_id = str(turn["id"])
        row = await self.s.get(TurnORM, turn_id)
        if row is None:
            row = TurnORM(
                id=turn_id,
                session_id=str(turn["session_id"]),
                turn_number=int(turn.get("turn_number", 0)),
                player_input=str(turn.get("player_input", "")),
                idempotency_key=turn.get("idempotency_key"),
                status=str(turn.get("status", "CANONICAL_COMMITTED")),
                world_minute_before=int(turn.get("world_minute_before", 0)),
                world_minute_after=int(turn.get("world_minute_after", 0)),
                canonical_payload=turn.get("canonical_payload", {}),
                last_error=turn.get("last_error", {}),
                result=turn.get("result", {}),
            )
            self.s.add(row)
            return
        row.status = str(turn.get("status", row.status))
        row.world_minute_after = int(turn.get("world_minute_after", row.world_minute_after))
        row.canonical_payload = turn.get("canonical_payload", row.canonical_payload)
        row.last_error = turn.get("last_error", row.last_error)
        row.result = turn.get("result", row.result)

    async def get(self, turn_id: str) -> dict[str, Any] | None:
        row = await self.s.get(TurnORM, turn_id)
        return _turn_to_dict(row) if row else None

    async def get_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        row = await self._one(sa.select(TurnORM).where(TurnORM.idempotency_key == key))
        return _turn_to_dict(row) if row else None

    async def list_for_session(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self._scalars(
            sa.select(TurnORM)
            .where(TurnORM.session_id == session_id)
            .order_by(TurnORM.turn_number.desc())
            .limit(limit)
        )
        return [_turn_to_dict(r) for r in reversed(list(rows))]

    async def append_narrative(self, segment: NarrativeSegment) -> None:
        self.s.add(m.narrative_to_orm(segment))

    async def list_narrative(self, session_id: str, limit: int = 10) -> list[NarrativeSegment]:
        rows = await self._scalars(
            sa.select(NarrativeSegmentORM)
            .where(NarrativeSegmentORM.session_id == session_id)
            .order_by(NarrativeSegmentORM.created_at.desc())
            .limit(limit)
        )
        return [m.narrative_to_domain(r) for r in reversed(list(rows))]

    async def save_trace(self, trace: dict[str, Any]) -> None:
        turn_id = str(trace["turn_id"])
        row = await self.s.get(TurnTraceORM, turn_id)
        if row is None:
            self.s.add(
                TurnTraceORM(
                    turn_id=turn_id,
                    request_id=str(trace.get("request_id", "")),
                    session_id=str(trace.get("session_id", "")),
                    world_id=str(trace.get("world_id", "")),
                    payload=trace,
                )
            )
            return
        row.request_id = str(trace.get("request_id", row.request_id))
        row.session_id = str(trace.get("session_id", row.session_id))
        row.world_id = str(trace.get("world_id", row.world_id))
        row.payload = trace

    async def get_trace(self, turn_id: str) -> dict[str, Any] | None:
        row = await self.s.get(TurnTraceORM, turn_id)
        return dict(row.payload) if row else None


def _turn_to_dict(row: TurnORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "turn_number": row.turn_number,
        "player_input": row.player_input,
        "idempotency_key": row.idempotency_key,
        "status": row.status,
        "world_minute_before": row.world_minute_before,
        "world_minute_after": row.world_minute_after,
        "canonical_payload": row.canonical_payload or {},
        "last_error": row.last_error or {},
        "result": row.result or {},
    }


# ---------------------------------------------------------------------------
class SqlUnitOfWork:
    """One database transaction per turn (Prompt section 58)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.worlds = SqlWorldRepo(session)
        self.locations = SqlLocationRepo(session)
        self.factions = SqlFactionRepo(session)
        self.characters = SqlCharacterRepo(session)
        self.relationships = SqlRelationshipRepo(session)
        self.knowledge = SqlKnowledgeRepo(session)
        self.memories = SqlMemoryRepo(session)
        self.items = SqlItemRepo(session)
        self.skills = SqlSkillRepo(session)
        self.quests = SqlQuestRepo(session)
        self.events = SqlEventRepo(session)
        self.plot_threads = SqlPlotThreadRepo(session)
        self.director_events = SqlDirectorEventRepo(session)
        self.sessions = SqlSessionRepo(session)
        self.turns = SqlTurnRepo(session)
        self.world_state = SqlWorldStateRepository(session)

    async def __aenter__(self) -> SqlUnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    # -- the write path -----------------------------------------------------
    async def apply(self, change_set: ChangeSet) -> None:
        for change in change_set.changes:
            await self._apply_one(change)
        for event in change_set.events:
            self.session.add(m.event_to_orm(event))
        for rc in change_set.relationship_changes:
            self.session.add(m.relationship_change_to_orm(rc))
        for memory in change_set.memories:
            self.session.add(m.memory_to_orm(memory))
        for director_event in change_set.director_events:
            await self._upsert_director_event(director_event)
        await self.session.flush()

    async def _upsert_director_event(self, director_event: DirectorEvent) -> None:
        row = await self.session.get(DirectorEventORM, director_event.id)
        incoming = m.director_event_to_orm(director_event)
        if row is None:
            self.session.add(incoming)
            return
        for column in DirectorEventORM.__table__.columns:
            if column.name in {"id", "created_at", "updated_at"}:
                continue
            setattr(row, column.name, getattr(incoming, column.name))

    async def _apply_one(self, change) -> None:
        s = self.session
        kind = change.kind
        if kind is ChangeKind.CHARACTER_SPAWN:
            spawned_character = Character.model_validate(change.payload["character"])
            if await s.get(CharacterORM, spawned_character.id) is None:
                s.add(m.character_to_orm(spawned_character))
        elif kind is ChangeKind.LOCATION_SPAWN:
            spawned_location = Location.model_validate(change.payload["location"])
            if await s.get(LocationORM, spawned_location.id) is None:
                s.add(m.location_to_orm(spawned_location))
        elif kind is ChangeKind.CHARACTER_FIELD:
            row = await s.get(CharacterORM, change.target_id)
            if row is None:
                raise EngineError(f"unknown character {change.target_id}")
            setattr(row, change.field, change.after)
        elif kind is ChangeKind.CHARACTER_LOCATION:
            row = await s.get(CharacterORM, change.target_id)
            if row is not None:
                row.location_id = change.after
                location = await s.get(LocationORM, str(change.after))
                row.location_key = location.key if location else None
        elif kind is ChangeKind.CHARACTER_DEATH:
            row = await s.get(CharacterORM, change.target_id)
            if row is not None:
                row.alive = False
                row.health = 0
                row.death_event_id = change.payload.get("death_event_id")
        elif kind is ChangeKind.CHARACTER_EMOTION:
            row = await s.get(CharacterORM, change.target_id)
            if row is not None:
                row.current_emotion = {**(row.current_emotion or {}), **change.payload}
        elif kind is ChangeKind.CHARACTER_GOALS:
            row = await s.get(CharacterORM, change.target_id)
            if row is not None:
                if "short_term_goals" in change.payload:
                    row.short_term_goals = list(change.payload["short_term_goals"])
                if "long_term_goal" in change.payload:
                    row.long_term_goal = str(change.payload["long_term_goal"])
                if "goal_lifecycle" in change.payload:
                    row.goal_lifecycle = dict(change.payload["goal_lifecycle"] or {})
        elif kind is ChangeKind.RELATIONSHIP_DELTA:
            await self._apply_relationship(change)
        elif kind is ChangeKind.INVENTORY_ADD:
            await self._inventory_add(change)
        elif kind is ChangeKind.INVENTORY_REMOVE:
            await self._inventory_remove(change)
        elif kind is ChangeKind.SKILL_LEARN:
            existing = await self.skills.get_for_character(
                change.target_id, str(change.payload["skill_key"])
            )
            if existing is None:
                s.add(
                    CharacterSkillORM(
                        id=new_id(),
                        character_id=change.target_id,
                        skill_key=str(change.payload["skill_key"]),
                        mastery=0.1,
                    )
                )
        elif kind is ChangeKind.SKILL_USED:
            skill_row = (
                (
                    await s.execute(
                        sa.select(CharacterSkillORM).where(
                            CharacterSkillORM.character_id == change.target_id,
                            CharacterSkillORM.skill_key == str(change.payload["skill_key"]),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if skill_row is not None:
                skill_row.last_used_minute = int(change.payload.get("at_minute", 0))
                skill_row.mastery = min(1.0, skill_row.mastery + 0.005)
        elif kind is ChangeKind.KNOWLEDGE_SET:
            await self._knowledge_set(change)
        elif kind is ChangeKind.QUEST_STATUS:
            quest_row = await s.get(QuestORM, change.target_id)
            if quest_row is not None:
                quest_row.status = str(change.after)
        elif kind is ChangeKind.FACTION_FIELD:
            faction_row = await s.get(FactionORM, change.target_id)
            if faction_row is not None:
                setattr(faction_row, change.field, change.after)
        elif kind is ChangeKind.PLOT_THREAD_UPDATE:
            thread_row = await s.get(PlotThreadORM, change.target_id)
            if thread_row is not None:
                for field, value in change.payload.items():
                    if hasattr(thread_row, field):
                        setattr(thread_row, field, value)
        elif kind is ChangeKind.WORLD_TIME:
            world_row = await s.get(WorldORM, change.target_id)
            if world_row is not None:
                world_row.current_minute = int(change.after)
        elif kind is ChangeKind.WORLD_TENSION:
            tension_row = await s.get(WorldORM, change.target_id)
            if tension_row is not None:
                tension_row.tension_history = [
                    *(tension_row.tension_history or []),
                    tension_row.narrative_tension,
                ][-20:]
                tension_row.narrative_tension = float(change.after)
        elif kind is ChangeKind.LOCATION_FLAG:
            location_row = await s.get(LocationORM, change.target_id)
            if location_row is not None:
                location_row.location_metadata = {
                    **(location_row.location_metadata or {}),
                    **change.payload,
                }

    async def _apply_relationship(self, change) -> None:
        s = self.session
        a_id, b_id = change.target_id, str(change.payload["other_id"])
        row = (
            (
                await s.execute(
                    sa.select(RelationshipORM).where(
                        RelationshipORM.character_a_id == a_id,
                        RelationshipORM.character_b_id == b_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            actor = await s.get(CharacterORM, a_id)
            row = RelationshipORM(
                id=new_id(),
                world_id=actor.world_id if actor else "",
                character_a_id=a_id,
                character_b_id=b_id,
            )
            s.add(row)
        for dim, delta in (change.payload.get("deltas") or {}).items():
            if hasattr(row, dim):
                setattr(row, dim, int(getattr(row, dim) or 0) + int(delta))
        row.interaction_count = int(row.interaction_count or 0) + 1

    async def _inventory_add(self, change) -> None:
        s = self.session
        item_key = str(change.payload["item_key"])
        quantity = int(change.payload.get("quantity", 1))
        row = (
            (
                await s.execute(
                    sa.select(InventoryItemORM).where(
                        InventoryItemORM.character_id == change.target_id,
                        InventoryItemORM.item_key == item_key,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            s.add(
                InventoryItemORM(
                    id=new_id(),
                    character_id=change.target_id,
                    item_key=item_key,
                    quantity=quantity,
                )
            )
        else:
            row.quantity += quantity

    async def _inventory_remove(self, change) -> None:
        s = self.session
        item_key = str(change.payload["item_key"])
        quantity = int(change.payload.get("quantity", 1))
        row = (
            (
                await s.execute(
                    sa.select(InventoryItemORM).where(
                        InventoryItemORM.character_id == change.target_id,
                        InventoryItemORM.item_key == item_key,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None or row.quantity < quantity:
            raise EngineError(
                f"cannot remove {quantity} of {item_key}", character_id=change.target_id
            )
        row.quantity -= quantity
        if row.quantity <= 0:
            await s.delete(row)

    async def _knowledge_set(self, change) -> None:
        s = self.session
        fact_id = str(change.payload["fact_id"])
        row = (
            (
                await s.execute(
                    sa.select(CharacterKnowledgeORM).where(
                        CharacterKnowledgeORM.character_id == change.target_id,
                        CharacterKnowledgeORM.fact_id == fact_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            s.add(
                CharacterKnowledgeORM(
                    id=new_id(),
                    character_id=change.target_id,
                    fact_id=fact_id,
                    knowledge_state=str(change.payload["knowledge_state"]),
                    confidence=float(change.payload.get("confidence", 0.5)),
                    source=str(change.payload.get("source", "INFERRED")),
                    source_character_id=change.payload.get("source_character_id"),
                    learned_at_minute=int(change.payload.get("learned_at_minute", 0)),
                )
            )
        else:
            row.knowledge_state = str(change.payload["knowledge_state"])
            row.confidence = float(change.payload.get("confidence", row.confidence))
            row.source = str(change.payload.get("source", row.source))
            row.learned_at_minute = int(
                change.payload.get("learned_at_minute", row.learned_at_minute)
            )

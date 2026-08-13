"""Save and load: freezing a whole world, and putting it back.

A save here is a complete copy of every row that belongs to a session - world,
places, people, relationships, beliefs, memories, the event log, every turn and
every chapter of prose. Loading deletes what is there now and writes the copy
back.

The obvious alternative, rewinding by reversing state changes, does not work in
this engine: the event log is append-only, memories are projections of it, and
prose is not reversible at all. Copying is the only way to get a restore point
that is actually the world the player saw. This world is a few hundred rows, so
the honest approach is also the cheap one.

Everything here is keyed off two ids. Rows that belong to the *world* (places,
people, events) are matched on ``world_id``; rows that belong to the *story*
(turns, chapters, traces) are matched on ``session_id``. A save carries both.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

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
    SaveSlotORM,
    SkillORM,
    TurnORM,
    TurnTraceORM,
    WorldORM,
)
from engine.core.ids import new_id

#: Tables scoped to the world, matched on ``world_id``.
#: Typed loosely on purpose: these are iterated generically, and the point of
#: the generic pass is that adding a table needs no new code here.
_WORLD_TABLES: tuple[Any, ...] = (
    LocationORM,
    FactionORM,
    ItemORM,
    SkillORM,
    CharacterORM,
    RelationshipORM,
    RelationshipChangeORM,
    FactORM,
    QuestORM,
    PlotThreadORM,
    DirectorEventORM,
    MemoryORM,
    EventORM,
)

#: Tables scoped to the session, matched on ``session_id``.
_SESSION_TABLES: tuple[Any, ...] = (
    GameSessionORM,
    TurnORM,
    TurnTraceORM,
    NarrativeSegmentORM,
)

#: Tables reached through a character rather than carrying an id of their own.
_BY_CHARACTER: tuple[Any, ...] = (
    InventoryItemORM,
    CharacterSkillORM,
    CharacterKnowledgeORM,
)


@dataclass(slots=True)
class SaveHeader:
    """What the save list shows, without loading the payload."""

    id: str
    session_id: str
    world_id: str
    name: str
    player_name: str
    turn_number: int
    time_label: str
    location_name: str
    excerpt: str
    created_at: dt.datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "world_id": self.world_id,
            "name": self.name,
            "player_name": self.player_name,
            "turn_number": self.turn_number,
            "time_label": self.time_label,
            "location_name": self.location_name,
            "excerpt": self.excerpt,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def _row_to_dict(row: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        out[column.name] = value.isoformat() if isinstance(value, dt.datetime) else value
    return out


def _coerce(model: Any, data: dict[str, Any]) -> dict[str, Any]:
    """Restore column types that JSON flattened on the way out."""
    out: dict[str, Any] = {}
    for column in model.__table__.columns:
        if column.name not in data:
            continue
        value = data[column.name]
        if isinstance(column.type, sa.DateTime) and isinstance(value, str):
            value = dt.datetime.fromisoformat(value)
        out[column.name] = value
    return out


class SaveService:
    """Captures and restores whole sessions. SQL only, by design."""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    # ------------------------------------------------------------------
    async def capture(
        self,
        *,
        session_id: str,
        world_id: str,
        name: str,
        player_name: str = "",
        turn_number: int = 0,
        world_minute: int = 0,
        time_label: str = "",
        location_name: str = "",
        excerpt: str = "",
        user_id: str | None = None,
        playthrough_id: str | None = None,
    ) -> SaveHeader:
        payload: dict[str, list[dict[str, Any]]] = {}

        world = await self.s.get(WorldORM, world_id)
        payload[WorldORM.__tablename__] = [_row_to_dict(world)] if world else []

        for model in _WORLD_TABLES:
            rows = await self._select(model, model.world_id == world_id)
            payload[model.__tablename__] = [_row_to_dict(r) for r in rows]

        for model in _SESSION_TABLES:
            column = model.id if model is GameSessionORM else model.session_id
            rows = await self._select(model, column == session_id)
            payload[model.__tablename__] = [_row_to_dict(r) for r in rows]

        # Per-character tables have no world column of their own.
        character_ids = [
            row["id"] for row in payload.get(CharacterORM.__tablename__, [])
        ]
        for model in _BY_CHARACTER:
            rows = (
                await self._select(model, model.character_id.in_(character_ids))
                if character_ids
                else []
            )
            payload[model.__tablename__] = [_row_to_dict(r) for r in rows]

        slot = SaveSlotORM(
            id=new_id(),
            user_id=user_id,
            playthrough_id=playthrough_id,
            session_id=session_id,
            world_id=world_id,
            name=name.strip()[:80],
            player_name=player_name[:80],
            turn_number=turn_number,
            world_minute=world_minute,
            time_label=time_label[:120],
            location_name=location_name[:120],
            excerpt=excerpt[:400],
            payload=payload,
        )
        self.s.add(slot)
        await self.s.flush()
        return _header(slot)

    # ------------------------------------------------------------------
    async def restore(self, save_id: str) -> SaveHeader | None:
        """Put the world back exactly as it was when the save was taken."""
        slot = await self.s.get(SaveSlotORM, save_id)
        if slot is None:
            return None

        payload = dict(slot.payload or {})
        # Delete first, in an order that never leaves a half-restored world
        # visible: everything belonging to this session and world goes, then
        # the snapshot is written back whole.
        for model in (*_SESSION_TABLES, *_WORLD_TABLES):
            column = (
                model.id
                if model is GameSessionORM
                else (
                    model.session_id
                    if model in _SESSION_TABLES
                    else model.world_id
                )
            )
            key = slot.session_id if model in _SESSION_TABLES else slot.world_id
            await self.s.execute(sa.delete(model).where(column == key))

        current_characters = await self._select(
            CharacterORM, CharacterORM.world_id == slot.world_id
        )
        stale_ids = [c.id for c in current_characters] + [
            row["id"] for row in payload.get(CharacterORM.__tablename__, [])
        ]
        for model in _BY_CHARACTER:
            if stale_ids:
                await self.s.execute(
                    sa.delete(model).where(model.character_id.in_(stale_ids))
                )

        world = await self.s.get(WorldORM, slot.world_id)
        if world is not None:
            await self.s.delete(world)
        await self.s.flush()

        for row in payload.get(WorldORM.__tablename__, []):
            self.s.add(WorldORM(**_coerce(WorldORM, row)))
        for model in (*_WORLD_TABLES, *_SESSION_TABLES, *_BY_CHARACTER):
            for row in payload.get(model.__tablename__, []):
                self.s.add(model(**_coerce(model, row)))

        await self.s.flush()
        return _header(slot)

    # ------------------------------------------------------------------
    async def list_for_session(self, session_id: str) -> list[SaveHeader]:
        rows = await self._select(
            SaveSlotORM,
            SaveSlotORM.session_id == session_id,
            order_by=SaveSlotORM.created_at.desc(),
        )
        return [_header(r) for r in rows]

    async def list_all(self, limit: int = 50) -> list[SaveHeader]:
        rows = await self._select(
            SaveSlotORM, None, order_by=SaveSlotORM.created_at.desc(), limit=limit
        )
        return [_header(r) for r in rows]

    async def delete(self, save_id: str) -> bool:
        slot = await self.s.get(SaveSlotORM, save_id)
        if slot is None:
            return False
        await self.s.delete(slot)
        await self.s.flush()
        return True

    # ------------------------------------------------------------------
    async def _select(
        self, model: Any, where: Any = None, *, order_by: Any = None, limit: int | None = None
    ) -> list[Any]:
        stmt: Any = sa.select(model)
        if where is not None:
            stmt = stmt.where(where)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.s.execute(stmt)
        return list(result.scalars().all())


def _header(slot: SaveSlotORM) -> SaveHeader:
    return SaveHeader(
        id=slot.id,
        session_id=slot.session_id,
        world_id=slot.world_id,
        name=slot.name,
        player_name=slot.player_name,
        turn_number=slot.turn_number,
        time_label=slot.time_label,
        location_name=slot.location_name,
        excerpt=slot.excerpt,
        created_at=slot.created_at,
    )

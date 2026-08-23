"""Single-round-trip SQL adapter for the turn-start world snapshot."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from database import mappers as m
from database.models.orm import (
    CharacterORM,
    CharacterSkillORM,
    FactionORM,
    InventoryItemORM,
    LocationORM,
    PlotThreadORM,
    QuestORM,
    RelationshipORM,
    StoryClockORM,
    WorldORM,
)
from engine.core.snapshots import WorldStateSnapshot


def _json_row(model: type[Any], dialect_name: str) -> Any:
    """Render one ORM row as JSON using the active database's native function."""

    arguments: list[Any] = []
    for column in model.__table__.columns:
        arguments.extend((column.name, column))
    if dialect_name == "postgresql":
        return sa.func.jsonb_build_object(*arguments)
    return sa.func.json_object(*arguments)


def _branch(
    kind: str,
    model: type[Any],
    dialect_name: str,
    *criteria: Any,
) -> Any:
    return (
        sa.select(
            sa.literal(kind).label("kind"),
            _json_row(model, dialect_name).label("payload"),
        )
        .select_from(model)
        .where(*criteria)
    )


def _decode_payload(model: type[Any], raw: Any) -> dict[str, Any]:
    payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
    for column in model.__table__.columns:
        value = payload.get(column.name)
        if isinstance(column.type, sa.JSON) and isinstance(value, str):
            with suppress(json.JSONDecodeError):
                payload[column.name] = json.loads(value)
        elif isinstance(column.type, sa.Boolean) and value is not None:
            payload[column.name] = bool(value)
    return payload


class SqlWorldStateRepository:
    """Load all turn-start aggregates with one statement and one AsyncSession.

    Each UNION branch retains explicit ownership keys, so PostgreSQL RLS still
    evaluates every underlying table. Unlike collection JOIN eager loading,
    this does not create a Cartesian product between locations, factions,
    quests, and the player's other collections.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load(self, world_id: str, player_id: str) -> WorldStateSnapshot:
        dialect_name = self.session.get_bind().dialect.name
        player_location = (
            sa.select(CharacterORM.location_id)
            .where(CharacterORM.id == player_id, CharacterORM.world_id == world_id)
            .scalar_subquery()
        )
        valid_player = sa.exists(
            sa.select(CharacterORM.id).where(
                CharacterORM.id == player_id,
                CharacterORM.world_id == world_id,
            )
        )
        statement = sa.union_all(
            _branch("world", WorldORM, dialect_name, WorldORM.id == world_id),
            _branch(
                "player",
                CharacterORM,
                dialect_name,
                CharacterORM.id == player_id,
                CharacterORM.world_id == world_id,
            ),
            _branch(
                "location",
                LocationORM,
                dialect_name,
                LocationORM.world_id == world_id,
            ),
            _branch(
                "present_character",
                CharacterORM,
                dialect_name,
                CharacterORM.world_id == world_id,
                CharacterORM.location_id == player_location,
                CharacterORM.id != player_id,
                CharacterORM.alive.is_(True),
            ),
            _branch(
                "faction",
                FactionORM,
                dialect_name,
                FactionORM.world_id == world_id,
            ),
            _branch(
                "inventory",
                InventoryItemORM,
                dialect_name,
                InventoryItemORM.character_id == player_id,
                valid_player,
            ),
            _branch(
                "skill",
                CharacterSkillORM,
                dialect_name,
                CharacterSkillORM.character_id == player_id,
                valid_player,
            ),
            # Both directions. Interactions write the NPC -> player row, so
            # loading only player -> NPC left the narrator, the declarative
            # rules and the relationship readout all seeing a world where the
            # player had never met anybody.
            _branch(
                "relationship",
                RelationshipORM,
                dialect_name,
                RelationshipORM.world_id == world_id,
                sa.or_(
                    RelationshipORM.character_a_id == player_id,
                    RelationshipORM.character_b_id == player_id,
                ),
            ),
            _branch("quest", QuestORM, dialect_name, QuestORM.world_id == world_id),
            _branch(
                "plot_thread",
                PlotThreadORM,
                dialect_name,
                PlotThreadORM.world_id == world_id,
            ),
            _branch("clock", StoryClockORM, dialect_name, StoryClockORM.world_id == world_id),
        )
        rows = (await self.session.execute(statement)).all()
        snapshot = WorldStateSnapshot()
        for kind, raw_payload in rows:
            if kind == "world":
                snapshot.world = m.world_to_domain(
                    WorldORM(**_decode_payload(WorldORM, raw_payload))
                )
            elif kind == "player":
                snapshot.player = m.character_to_domain(
                    CharacterORM(**_decode_payload(CharacterORM, raw_payload))
                )
            elif kind == "location":
                snapshot.locations.append(
                    m.location_to_domain(LocationORM(**_decode_payload(LocationORM, raw_payload)))
                )
            elif kind == "present_character":
                snapshot.present_characters.append(
                    m.character_to_domain(
                        CharacterORM(**_decode_payload(CharacterORM, raw_payload))
                    )
                )
            elif kind == "faction":
                snapshot.factions.append(
                    m.faction_to_domain(FactionORM(**_decode_payload(FactionORM, raw_payload)))
                )
            elif kind == "inventory":
                snapshot.inventory.append(
                    m.inventory_to_domain(
                        InventoryItemORM(**_decode_payload(InventoryItemORM, raw_payload))
                    )
                )
            elif kind == "skill":
                snapshot.skills.append(
                    m.character_skill_to_domain(
                        CharacterSkillORM(**_decode_payload(CharacterSkillORM, raw_payload))
                    )
                )
            elif kind == "relationship":
                snapshot.relationships.append(
                    m.relationship_to_domain(
                        RelationshipORM(**_decode_payload(RelationshipORM, raw_payload))
                    )
                )
            elif kind == "quest":
                snapshot.quests.append(
                    m.quest_to_domain(QuestORM(**_decode_payload(QuestORM, raw_payload)))
                )
            elif kind == "plot_thread":
                snapshot.plot_threads.append(
                    m.thread_to_domain(PlotThreadORM(**_decode_payload(PlotThreadORM, raw_payload)))
                )
            elif kind == "clock":
                snapshot.clocks.append(
                    m.clock_to_domain(StoryClockORM(**_decode_payload(StoryClockORM, raw_payload)))
                )
        return snapshot

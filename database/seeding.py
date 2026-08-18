"""Persist a SeedBundle into SQL."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from database import mappers as m
from database.models.orm import WorldORM
from engine.world.seeder import SeedBundle


async def persist_bundle(session: AsyncSession, bundle: SeedBundle) -> str:
    """Write a freshly built world. Idempotent on world id."""
    existing = await session.get(WorldORM, bundle.world.id)
    if existing is not None:
        return bundle.world.id

    # Flush explicit dependency layers. SQLite's permissive test setup and the
    # ORM unit of work can otherwise hide insertion-order failures that a real
    # PostgreSQL foreign key rejects on a fresh database.
    session.add(m.world_to_orm(bundle.world))
    await session.flush()

    for loc in bundle.locations:
        session.add(m.location_to_orm(loc))
    for faction in bundle.factions:
        session.add(m.faction_to_orm(faction))
    for item in bundle.items:
        session.add(m.item_to_orm(item))
    for skill in bundle.skills:
        session.add(m.skill_to_orm(skill))
    await session.flush()

    for character in bundle.characters:
        session.add(m.character_to_orm(character))
    for fact in bundle.facts:
        session.add(m.fact_to_orm(fact))
    for quest in bundle.quests:
        session.add(m.quest_to_orm(quest))
    for thread in bundle.plot_threads:
        session.add(m.thread_to_orm(thread))
    for clock in bundle.clocks:
        session.add(m.clock_to_orm(clock))
    await session.flush()

    for rel in bundle.relationships:
        session.add(m.relationship_to_orm(rel))
    for knowledge in bundle.knowledge:
        session.add(m.knowledge_to_orm(knowledge))
    for inv in bundle.inventory:
        session.add(m.inventory_to_orm(inv))
    for cskill in bundle.character_skills:
        session.add(m.character_skill_to_orm(cskill))
    for director_event in bundle.director_events:
        session.add(m.director_event_to_orm(director_event))
    if bundle.session is not None:
        session.add(m.session_to_orm(bundle.session))

    await session.flush()
    return bundle.world.id


async def world_exists(session: AsyncSession, world_id: str) -> bool:
    result = await session.execute(sa.select(WorldORM.id).where(WorldORM.id == world_id))
    return result.scalars().first() is not None

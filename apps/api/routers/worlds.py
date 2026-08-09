"""World and character endpoints (Prompt section 50)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from apps.api.deps import pack_dep, uow_dep
from apps.api.schemas import (
    CharacterSummary,
    CreateCharacterRequest,
    CreateWorldRequest,
    MemoryView,
    RelationshipView,
    WorldSummary,
)
from database.repositories.sql import SqlUnitOfWork
from database.seeding import persist_bundle
from engine.contentpack.pack import ContentPack
from engine.core.models import Character, World
from engine.world.clock import WorldClock
from engine.world.seeder import PlayerSpec, build_world

router = APIRouter(tags=["world"])


# ---------------------------------------------------------------------------
@router.post("/worlds", response_model=WorldSummary, status_code=201)
async def create_world(
    body: CreateWorldRequest,
    uow: SqlUnitOfWork = Depends(uow_dep),
    pack: ContentPack = Depends(pack_dep),
) -> WorldSummary:
    bundle = build_world(pack, world_seed=body.world_seed, world_name=body.name)
    await persist_bundle(uow.session, bundle)
    await uow.commit()
    return await _world_summary(uow, pack, bundle.world)


@router.get("/worlds", response_model=list[WorldSummary])
async def list_worlds(
    uow: SqlUnitOfWork = Depends(uow_dep), pack: ContentPack = Depends(pack_dep)
) -> list[WorldSummary]:
    return [await _world_summary(uow, pack, w) for w in await uow.worlds.list_all()]


@router.get("/worlds/{world_id}", response_model=WorldSummary)
async def get_world(
    world_id: str, uow: SqlUnitOfWork = Depends(uow_dep), pack: ContentPack = Depends(pack_dep)
) -> WorldSummary:
    world = await uow.worlds.get(world_id)
    if world is None:
        raise HTTPException(status_code=404, detail="world not found")
    return await _world_summary(uow, pack, world)


# ---------------------------------------------------------------------------
@router.post("/characters", response_model=CharacterSummary, status_code=201)
async def create_character(
    body: CreateCharacterRequest,
    uow: SqlUnitOfWork = Depends(uow_dep),
    pack: ContentPack = Depends(pack_dep),
) -> CharacterSummary:
    """Create a player character inside an existing world."""
    world = await uow.worlds.get(body.world_id)
    if world is None:
        raise HTTPException(status_code=404, detail="world not found")

    bundle = build_world(
        pack,
        world_seed=world.world_seed,
        player=PlayerSpec(
            name=body.name,
            gender=body.gender,
            age=body.age,
            background=body.background,
            spiritual_root=body.spiritual_root,
            stats=body.stats,
        ),
    )
    player = bundle.character_by_key("player")
    if player is None:
        raise HTTPException(status_code=500, detail="failed to build the player character")

    existing = await uow.characters.get(player.id)
    if existing is None:
        from database import mappers as m

        uow.session.add(m.character_to_orm(player))
        for inv in bundle.inventory:
            if inv.character_id == player.id:
                uow.session.add(m.inventory_to_orm(inv))
        for skill in bundle.character_skills:
            if skill.character_id == player.id:
                uow.session.add(m.character_skill_to_orm(skill))
        await uow.commit()
        existing = player
    return await _character_summary(uow, pack, existing)


@router.get("/characters/{character_id}", response_model=CharacterSummary)
async def get_character(
    character_id: str,
    uow: SqlUnitOfWork = Depends(uow_dep),
    pack: ContentPack = Depends(pack_dep),
) -> CharacterSummary:
    character = await uow.characters.get(character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="character not found")
    return await _character_summary(uow, pack, character)


@router.get("/characters/{character_id}/relationships", response_model=list[RelationshipView])
async def get_relationships(
    character_id: str, uow: SqlUnitOfWork = Depends(uow_dep)
) -> list[RelationshipView]:
    from apps.api.routers.game import _relationships_for

    if await uow.characters.get(character_id) is None:
        raise HTTPException(status_code=404, detail="character not found")
    return await _relationships_for(uow, character_id)


@router.get("/characters/{character_id}/memories", response_model=list[MemoryView])
async def get_memories(
    character_id: str, limit: int = 50, uow: SqlUnitOfWork = Depends(uow_dep)
) -> list[MemoryView]:
    if await uow.characters.get(character_id) is None:
        raise HTTPException(status_code=404, detail="character not found")
    rows = await uow.memories.list_for_owner(character_id, limit=limit)
    return [
        MemoryView(
            id=m.id,
            memory_type=str(m.memory_type),
            memory_tag=str(m.memory_tag),
            summary=m.summary,
            importance=m.importance,
            emotional_valence=m.emotional_valence,
            created_at_minute=m.created_at_minute,
            related_characters=m.related_characters,
        )
        for m in rows
    ]


# ---------------------------------------------------------------------------
async def _world_summary(uow: SqlUnitOfWork, pack: ContentPack, world: World) -> WorldSummary:
    clock = WorldClock(world.calendar_config or pack.calendar)
    characters = await uow.characters.list_for_world(world.id, alive_only=False)
    locations = await uow.locations.list_for_world(world.id)
    return WorldSummary(
        id=world.id,
        name=world.name,
        description=world.description,
        content_pack=world.content_pack,
        world_seed=world.world_seed,
        current_minute=world.current_minute,
        time_label=clock.to_world_time(world.current_minute).label,
        narrative_tension=round(world.narrative_tension, 1),
        character_count=len(characters),
        location_count=len(locations),
    )


async def _character_summary(
    uow: SqlUnitOfWork, pack: ContentPack, character: Character
) -> CharacterSummary:
    location = (
        await uow.locations.get(character.location_id) if character.location_id else None
    )
    return CharacterSummary(
        id=character.id,
        key=character.key,
        name=character.name,
        title=character.title,
        character_type=str(character.character_type),
        realm=character.realm,
        realm_display=pack.realms.display(character.realm, character.realm_stage),
        realm_stage=character.realm_stage,
        cultivation_progress=round(character.cultivation_progress, 4),
        health=[character.health, character.max_health],
        spiritual_power=[character.spiritual_power, character.max_spiritual_power],
        location_key=character.location_key,
        location_name=location.name if location else None,
        faction_key=character.faction_key,
        alive=character.alive,
        stats={
            "strength": character.strength,
            "agility": character.agility,
            "perception": character.perception,
            "intelligence": character.intelligence,
            "willpower": character.willpower,
            "charisma": character.charisma,
        },
        injuries=round(character.injuries, 3),
        mental_state=round(character.mental_state, 3),
    )


def summary_payload(world: World) -> dict[str, Any]:
    return {"id": world.id, "name": world.name}

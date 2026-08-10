"""Debug Panel and World Inspector (Prompt sections 52, 53).

The single most useful tool when building an AI game: see the intent, the rule
verdict, the dice, every NPC decision and the exact context each agent was
given - without opening a SQL client.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from apps.api.deps import pack_dep, settings_dep, uow_dep
from apps.api.routers.worlds import _character_summary, _world_summary
from apps.api.schemas import EventView, InspectorView
from database.repositories.sql import SqlUnitOfWork
from engine.contentpack.pack import ContentPack
from engine.core.config import Settings
from engine.director.tension import TensionModel

router = APIRouter(tags=["debug"])


@router.get("/debug/turn/{turn_id}")
async def get_turn_trace(
    turn_id: str,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    if not settings.debug_mode:
        raise HTTPException(status_code=403, detail="debug mode is disabled")
    trace = await uow.turns.get_trace(turn_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace


@router.get("/debug/session/{session_id}/turns")
async def list_session_turns(
    session_id: str,
    limit: int = 30,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> list[dict[str, Any]]:
    if not settings.debug_mode:
        raise HTTPException(status_code=403, detail="debug mode is disabled")
    turns = await uow.turns.list_for_session(session_id, limit=limit)
    return [
        {
            "turn_id": t["id"],
            "turn_number": t["turn_number"],
            "player_input": t["player_input"],
            "world_minute_before": t["world_minute_before"],
            "world_minute_after": t["world_minute_after"],
        }
        for t in turns
    ]


@router.get("/admin/world/{world_id}/inspector", response_model=InspectorView)
async def world_inspector(
    world_id: str,
    uow: SqlUnitOfWork = Depends(uow_dep),
    pack: ContentPack = Depends(pack_dep),
) -> InspectorView:
    world = await uow.worlds.get(world_id)
    if world is None:
        raise HTTPException(status_code=404, detail="world not found")

    characters = await uow.characters.list_for_world(world_id, alive_only=False)
    factions = await uow.factions.list_for_world(world_id)
    threads = await uow.plot_threads.list_for_world(world_id)
    director_events = await uow.director_events.list_for_world(world_id, limit=40)
    events = await uow.events.list_recent(world_id, limit=40)
    tension = TensionModel(pack)

    return InspectorView(
        world=await _world_summary(uow, pack, world),
        characters=[await _character_summary(uow, pack, c) for c in characters],
        factions=[
            {
                "key": f.key,
                "name": f.name,
                "resources": f.resources,
                "member_count": f.member_count,
                "military_power": round(f.military_power, 2),
                "reputation": round(f.reputation, 2),
                "leader": f.leader_key,
                "enemies": f.enemies,
                "alliances": f.alliances,
                "goals": f.goals,
            }
            for f in factions
        ],
        plot_threads=[
            {
                "key": t.key,
                "name": t.name,
                "status": str(t.status),
                "stage": t.stage,
                "importance": t.importance,
                "participants": t.participants,
                "unresolved_questions": t.unresolved_questions,
                "foreshadowing": t.foreshadowing,
                "last_advanced_minute": t.last_advanced_minute,
            }
            for t in threads
        ],
        director_events=[
            {
                "id": event.id,
                "status": str(event.status),
                "event_type": event.event_type,
                "source_plot_thread": event.source_plot_thread_key,
                "scheduled_for_minute": event.scheduled_for_minute,
                "canonical_event_id": event.canonical_event_id,
                "cancellation_reason": event.cancellation_reason,
                "history": [transition.model_dump(mode="json") for transition in event.history],
            }
            for event in director_events
        ],
        recent_events=[
            EventView(
                id=e.id,
                event_type=e.event_type,
                actor_id=e.actor_id,
                world_minute=e.world_minute,
                importance=round(e.importance, 2),
                visibility=str(e.visibility),
                summary=str(e.payload.get("summary", "")),
                causes=e.causes,
            )
            for e in events
        ],
        tension=tension.describe(world.narrative_tension, world.tension_history),
    )


@router.get("/admin/character/{character_id}/knowledge")
async def character_knowledge(
    character_id: str, uow: SqlUnitOfWork = Depends(uow_dep)
) -> list[dict[str, Any]]:
    """Inspector-only view. Note it still shows beliefs, not truth values."""
    if await uow.characters.get(character_id) is None:
        raise HTTPException(status_code=404, detail="character not found")
    rows = await uow.knowledge.list_known(character_id)
    return [
        {
            "fact_key": fact.key,
            "statement": fact.statement,
            "state": str(knowledge.knowledge_state),
            "confidence": round(knowledge.confidence, 3),
            "source": str(knowledge.source),
            "learned_at_minute": knowledge.learned_at_minute,
        }
        for knowledge, fact in rows
    ]


@router.get("/admin/world/{world_id}/events")
async def world_events(
    world_id: str, limit: int = 100, uow: SqlUnitOfWork = Depends(uow_dep)
) -> list[EventView]:
    events = await uow.events.list_recent(world_id, limit=limit)
    return [
        EventView(
            id=e.id,
            event_type=e.event_type,
            actor_id=e.actor_id,
            world_minute=e.world_minute,
            importance=round(e.importance, 2),
            visibility=str(e.visibility),
            summary=str(e.payload.get("summary", "")),
            causes=e.causes,
        )
        for e in events
    ]

"""Game endpoints (Prompt section 50)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from apps.api.deps import orchestrator_dep, pack_dep, settings_dep, uow_dep
from apps.api.schemas import (
    ActionRequest,
    CreateSaveRequest,
    HistoryEntry,
    InventoryView,
    MemoryView,
    OpeningView,
    QuestView,
    RelationshipView,
    SaveView,
    StartGameRequest,
    StartGameResponse,
)
from database.repositories.sql import SqlUnitOfWork
from database.saves import SaveService
from database.seeding import persist_bundle
from engine.contentpack.pack import ContentPack
from engine.core.config import Settings
from engine.core.errors import ConsistencyViolation, EngineError
from engine.core.ids import PLAYER_KEY
from engine.orchestrator.orchestrator import GameOrchestrator
from engine.orchestrator.turn import TurnRequest, TurnResult
from engine.world.seeder import PlayerSpec, build_world
from engine.world.state_view import build_world_state

router = APIRouter(prefix="/game", tags=["game"])

#: How often the action stream emits a comment while it has nothing to say.
#: Short enough to survive the usual 30-60s idle timeouts in between.
HEARTBEAT_SECONDS = 10.0


@router.post("/start", response_model=StartGameResponse)
async def start_game(
    body: StartGameRequest,
    uow: SqlUnitOfWork = Depends(uow_dep),
    pack: ContentPack = Depends(pack_dep),
    orchestrator: GameOrchestrator = Depends(orchestrator_dep),
) -> StartGameResponse:
    if not body.player_name.strip():
        raise HTTPException(status_code=422, detail="player_name is required")

    bundle = build_world(
        pack,
        world_seed=body.world_seed,
        player=PlayerSpec(
            name=body.player_name.strip(),
            gender=body.gender,
            age=body.age,
            background=body.background,
        ),
        session_seed=body.session_seed,
    )
    await persist_bundle(uow.session, bundle)
    await uow.commit()

    assert bundle.session is not None
    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None

    state = await build_world_state(uow, pack, bundle.world.id, player.id)
    prologue = await orchestrator.open_session(
        uow, bundle.session, state, max_chars=body.narrative_max_chars
    )
    if not prologue.text:
        location = state.location
        prologue.text = "\n\n".join(
            part
            for part in [
                location.description if location else "",
                orchestrator.d.narrative.template.query(state, "status"),
            ]
            if part
        )
    return StartGameResponse(
        session_id=bundle.session.id,
        world_id=bundle.world.id,
        player_character_id=player.id,
        opening=prologue.text,
        beat=prologue.beat,
        state=state.scene_summary(),
    )


@router.post("/{session_id}/action", response_model=TurnResult)
async def submit_action(
    session_id: str,
    body: ActionRequest,
    uow: SqlUnitOfWork = Depends(uow_dep),
    orchestrator: GameOrchestrator = Depends(orchestrator_dep),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TurnResult:
    request = TurnRequest(
        session_id=session_id,
        text=body.text,
        idempotency_key=body.idempotency_key or idempotency_key,
        debug=body.debug,
        narrative_max_chars=body.narrative_max_chars,
    )
    try:
        # The game is played in runs, not single actions: the character keeps
        # going until something needs the player (see GameOrchestrator.advance).
        return await orchestrator.advance(uow, request)
    except ConsistencyViolation as exc:
        raise HTTPException(status_code=500, detail=exc.to_dict()) from exc
    except EngineError as exc:
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc


@router.post("/{session_id}/action/stream")
async def submit_action_stream(
    session_id: str,
    body: ActionRequest,
    uow: SqlUnitOfWork = Depends(uow_dep),
    orchestrator: GameOrchestrator = Depends(orchestrator_dep),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StreamingResponse:
    """SSE: state first, prose second.

    Prompt section 49 - the world is fully adjudicated and committed before a
    single character of narrative is streamed.
    """
    async def events():
        # A run covers several turns and takes the better part of a minute, so
        # each committed step is announced as it lands. Without this the client
        # cannot tell a long chapter from a hung request.
        queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()

        async def on_step(index: int, step) -> None:
            await queue.put(
                (
                    "progress",
                    {
                        "step": index,
                        "action": step.action,
                        "summary": step.outcome.summary_key,
                        "minutes": step.minutes,
                    },
                )
            )

        async def on_chunk(text: str) -> None:
            await queue.put(("narrative", {"delta": text}))

        async def run() -> None:
            try:
                result = await orchestrator.advance(
                    uow,
                    TurnRequest(
                        session_id=session_id,
                        text=body.text,
                        idempotency_key=body.idempotency_key or idempotency_key,
                        debug=body.debug,
                        narrative_max_chars=body.narrative_max_chars,
                    ),
                    on_step,
                    on_chunk,
                )
                await queue.put(("result", result))
            except Exception as exc:  # the client is told, the run is not retried
                await queue.put(("failed", exc))
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
        result: TurnResult | None = None
        failure: Exception | None = None
        streamed = False
        # Bytes immediately, then a heartbeat while the world is being played
        # out. A chapter can take well over a minute, and the first ~30s of it
        # are silent; an idle connection that long is exactly what proxies and
        # browsers drop, which the player sees as "Failed to fetch".
        yield _sse("open", {"session_id": session_id})
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                kind, value = item
                if kind == "progress":
                    yield _sse("progress", value)
                elif kind == "narrative":
                    streamed = True
                    yield _sse("narrative", value)
                elif kind == "result":
                    result = value
                else:
                    failure = value
        finally:
            await task

        if failure is not None:
            yield _sse("error", {"message": str(failure)})
            return
        assert result is not None

        payload = result.model_dump(mode="json")
        narrative = payload.pop("narrative", "")
        # The prose has already gone out live unless the renderer degraded to
        # templates, which produce no chunks at all.
        if not streamed:
            for index in range(0, len(narrative), 18):
                yield _sse("narrative", {"delta": narrative[index : index + 18]})
        yield _sse("state", payload)
        yield _sse("done", {"turn_id": result.turn_id})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}/state")
async def get_state(
    session_id: str,
    uow: SqlUnitOfWork = Depends(uow_dep),
    pack: ContentPack = Depends(pack_dep),
) -> dict[str, Any]:
    session = await uow.sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    state = await build_world_state(uow, pack, session.world_id, session.player_character_id)
    summary = state.scene_summary()
    summary["session"] = {"id": session.id, "turn_number": session.turn_number}
    summary["narrative_tension"] = round(state.world.narrative_tension, 1)
    return summary


@router.get("/{session_id}/history", response_model=list[HistoryEntry])
async def get_history(
    session_id: str, limit: int = 30, uow: SqlUnitOfWork = Depends(uow_dep)
) -> list[HistoryEntry]:
    turns = await uow.turns.list_for_session(session_id, limit=limit)
    # A run commits one turn per step but produces one chapter, stored on the
    # step the player started. The others would render as blank rows.
    turns = [t for t in turns if (t.get("result") or {}).get("narrative")]
    return [
        HistoryEntry(
            turn_id=turn["id"],
            turn_number=turn["turn_number"],
            player_input=turn["player_input"],
            narrative=(turn.get("result") or {}).get("narrative", ""),
            world_minute_after=turn["world_minute_after"],
        )
        for turn in turns
    ]


@router.get("/{session_id}/inventory", response_model=list[InventoryView])
async def get_inventory(
    session_id: str,
    uow: SqlUnitOfWork = Depends(uow_dep),
    pack: ContentPack = Depends(pack_dep),
) -> list[InventoryView]:
    session = await uow.sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await uow.items.list_inventory(session.player_character_id)
    out: list[InventoryView] = []
    for row in rows:
        raw = pack.item(row.item_key) or {}
        out.append(
            InventoryView(
                item_key=row.item_key,
                name=str(raw.get("name", row.item_key)),
                item_type=str(raw.get("type", "misc")),
                rarity=str(raw.get("rarity", "common")),
                quantity=row.quantity,
                description=str(raw.get("description", "")).strip(),
                value=int(raw.get("value", 0)),
            )
        )
    return out


@router.get("/{session_id}/relationships", response_model=list[RelationshipView])
async def get_session_relationships(
    session_id: str, uow: SqlUnitOfWork = Depends(uow_dep)
) -> list[RelationshipView]:
    session = await uow.sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return await _relationships_for(uow, session.player_character_id)


@router.get("/{session_id}/quests", response_model=list[QuestView])
async def get_quests(
    session_id: str,
    uow: SqlUnitOfWork = Depends(uow_dep),
    pack: ContentPack = Depends(pack_dep),
) -> list[QuestView]:
    session = await uow.sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    quests = await uow.quests.list_for_world(session.world_id)
    labels = pack.vocabulary.get("status_labels", {}) or {}
    return [
        QuestView(
            key=q.key,
            name=q.name,
            status=str(q.status),
            # The panel shows this one; the raw status stays for the debug view.
            status_label=labels.get(str(q.status), str(q.status)),
            giver=q.giver_character_key,
            goal=q.goal,
            expires_at_minute=q.expires_at_minute,
        )
        for q in quests
    ]


async def _relationships_for(uow: SqlUnitOfWork, character_id: str) -> list[RelationshipView]:
    rows = await uow.relationships.list_for_character(character_id)
    out: list[RelationshipView] = []
    for rel in rows:
        other = await uow.characters.get(rel.character_b_id)
        out.append(
            RelationshipView(
                with_character_id=rel.character_b_id,
                with_key=other.key if other else "",
                with_name=other.display_name if other else "",
                dimensions=rel.as_dict(),
                tags=rel.tags,
                last_interaction_minute=rel.last_interaction_minute,
                interaction_count=rel.interaction_count,
            )
        )
    return out


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/settings/public")
async def public_settings(settings: Settings = Depends(settings_dep)) -> dict[str, Any]:
    """What the browser is allowed to know about the deployment."""
    return {
        "debug_mode": settings.debug_mode,
        "content_pack": settings.content_pack,
        "llm_provider": settings.llm_provider,
        "streaming": True,
    }


@router.get("/{session_id}/memories", response_model=list[MemoryView])
async def get_player_memories(
    session_id: str, limit: int = 50, uow: SqlUnitOfWork = Depends(uow_dep)
) -> list[MemoryView]:
    session = await uow.sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await uow.memories.list_for_owner(session.player_character_id, limit=limit)
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


# ---------------------------------------------------------------- save / load
@router.post("/{session_id}/saves", response_model=SaveView)
async def create_save(
    session_id: str,
    body: CreateSaveRequest,
    uow: SqlUnitOfWork = Depends(uow_dep),
    pack: ContentPack = Depends(pack_dep),
) -> SaveView:
    """Freeze the whole world and story at this moment."""
    session = await uow.sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    state = await build_world_state(uow, pack, session.world_id, session.player_character_id)
    segments = await uow.turns.list_narrative(session_id, limit=1)
    excerpt = segments[-1].text[-160:] if segments else ""

    header = await SaveService(uow.session).capture(
        session_id=session_id,
        world_id=session.world_id,
        name=body.name,
        player_name=state.player.name,
        turn_number=session.turn_number,
        world_minute=state.world.current_minute,
        time_label=state.time.label,
        location_name=state.location.name if state.location else "",
        excerpt=excerpt,
    )
    await uow.commit()
    return SaveView(**header.as_dict())


@router.get("/{session_id}/saves", response_model=list[SaveView])
async def list_saves(
    session_id: str, uow: SqlUnitOfWork = Depends(uow_dep)
) -> list[SaveView]:
    headers = await SaveService(uow.session).list_for_session(session_id)
    return [SaveView(**h.as_dict()) for h in headers]


@router.post("/saves/{save_id}/load", response_model=SaveView)
async def load_save(save_id: str, uow: SqlUnitOfWork = Depends(uow_dep)) -> SaveView:
    """Put the world back. Everything after this point is discarded."""
    header = await SaveService(uow.session).restore(save_id)
    if header is None:
        raise HTTPException(status_code=404, detail="save not found")
    await uow.commit()
    return SaveView(**header.as_dict())


@router.delete("/saves/{save_id}")
async def delete_save(save_id: str, uow: SqlUnitOfWork = Depends(uow_dep)) -> dict[str, bool]:
    deleted = await SaveService(uow.session).delete(save_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="save not found")
    await uow.commit()
    return {"deleted": True}


@router.get("/{session_id}/opening", response_model=OpeningView)
async def get_opening(
    session_id: str, uow: SqlUnitOfWork = Depends(uow_dep), pack: ContentPack = Depends(pack_dep)
) -> OpeningView:
    """The story so far, for a client rejoining a session after a load."""
    session = await uow.sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    state = await build_world_state(uow, pack, session.world_id, session.player_character_id)
    segments = await uow.turns.list_narrative(session_id, limit=30)
    turns = await uow.turns.list_for_session(session_id, limit=30)
    beat = next(
        (
            (t.get("result") or {}).get("beat")
            for t in reversed(turns)
            if (t.get("result") or {}).get("beat")
        ),
        None,
    )
    return OpeningView(
        session_id=session_id,
        world_id=session.world_id,
        player_character_id=session.player_character_id,
        chapters=[s.text for s in segments if s.text and s.kind != "beat"],
        beat=beat,
        state=state.scene_summary(),
    )

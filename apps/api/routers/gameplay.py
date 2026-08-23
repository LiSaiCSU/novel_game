"""Canonical playthrough actions and SSE delivery."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from apps.api.deps import settings_dep, uow_dep
from apps.api.product_analytics import record_product_event
from apps.api.routers.playthroughs import (
    PlayAction,
    _owned_playthrough,
    _runtime_for,
    narrative_max_chars,
)
from apps.api.runtime import release_runtime_service
from apps.api.security import Principal, require_csrf
from apps.api.tenancy import set_tenant_context
from database.models.platform import ContentReleaseORM
from database.repositories.sql import SqlUnitOfWork
from engine.core.config import Settings
from engine.core.errors import EngineError
from engine.core.logging import get_logger
from engine.orchestrator.turn import TurnRequest

router = APIRouter(tags=["v1-gameplay"])
logger = get_logger("gameplay")
HEARTBEAT_SECONDS = 12.0

#: Anything the engine raises on purpose is safe to show; anything else is a
#: bug, and its message may carry identifiers or provider detail the player
#: has no business seeing.
_GENERIC_ACTION_ERROR = "action failed"


def _player_facing_error(value: Any) -> str:
    if isinstance(value, HTTPException):
        return str(value.detail)
    if isinstance(value, EngineError):
        return value.message
    return _GENERIC_ACTION_ERROR


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/playthroughs/{playthrough_id}/actions")
async def playthrough_action(
    playthrough_id: str,
    body: PlayAction,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    play_lock = release_runtime_service.infrastructure.lock_backend(settings)
    async with play_lock.acquire(f"playthrough:{playthrough_id}"):
        await set_tenant_context(uow.session, principal.user_id)
        play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
        if play.status != "active":
            raise HTTPException(status_code=409, detail="playthrough is not active")
        release = await uow.session.get(ContentReleaseORM, play.release_id)
        session = await uow.sessions.get(play.game_session_id or "")
        if release is None or session is None:
            raise HTTPException(status_code=409, detail="playthrough runtime is incomplete")
        runtime = await _runtime_for(release, play, principal, uow, settings)
        try:
            result = await runtime.orchestrator.advance(
                uow,
                TurnRequest(
                    session_id=session.id,
                    text=body.text,
                    idempotency_key=body.idempotency_key,
                    narrative_max_chars=narrative_max_chars(play, body.narrative_max_chars),
                ),
            )
        finally:
            play.updated_at = datetime.now(UTC)
            await release_runtime_service.record_usage(runtime, principal.user_id, play.id, uow)
        await record_product_event(
            uow,
            principal,
            "action_completed",
            playthrough_id=play.id,
            release_id=release.id,
            dedupe_key=result.turn_id,
            properties={
                "turn_number": result.turn_number,
                "steps": result.steps,
                "degraded": result.degraded,
                "streamed": False,
            },
        )
        await uow.commit()
        return result.model_dump(mode="json")


@router.post("/playthroughs/{playthrough_id}/actions/stream")
async def stream_playthrough_action(
    playthrough_id: str,
    body: PlayAction,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> StreamingResponse:
    play_lock = release_runtime_service.infrastructure.lock_backend(settings)
    lock_context = play_lock.acquire(f"playthrough:{playthrough_id}")
    await lock_context.__aenter__()
    try:
        await set_tenant_context(uow.session, principal.user_id)
        play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
        if play.status != "active":
            raise HTTPException(status_code=409, detail="playthrough is not active")
        release = await uow.session.get(ContentReleaseORM, play.release_id)
        session = await uow.sessions.get(play.game_session_id or "")
        if release is None or session is None:
            raise HTTPException(status_code=409, detail="playthrough runtime is incomplete")
        runtime = await _runtime_for(release, play, principal, uow, settings)
    except BaseException:
        await lock_context.__aexit__(None, None, None)
        raise

    async def events() -> AsyncIterator[str]:
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
                result = await runtime.orchestrator.advance(
                    uow,
                    TurnRequest(
                        session_id=session.id,
                        text=body.text,
                        idempotency_key=body.idempotency_key,
                        narrative_max_chars=narrative_max_chars(play, body.narrative_max_chars),
                    ),
                    on_step,
                    on_chunk,
                )
                await record_product_event(
                    uow,
                    principal,
                    "action_completed",
                    playthrough_id=play.id,
                    release_id=release.id,
                    dedupe_key=result.turn_id,
                    properties={
                        "turn_number": result.turn_number,
                        "steps": result.steps,
                        "degraded": result.degraded,
                        "streamed": True,
                    },
                )
                await queue.put(("result", result))
            except Exception as exc:
                await queue.put(("error", exc))
            finally:
                try:
                    play.updated_at = datetime.now(UTC)
                    await release_runtime_service.record_usage(
                        runtime, principal.user_id, play.id, uow
                    )
                    await uow.commit()
                finally:
                    await queue.put(None)

        task = asyncio.create_task(run())
        result = None
        streamed = False
        yield _sse("open", {"playthrough_id": play.id})
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
                if kind == "error":
                    # The player gets a sentence they can act on; the stack
                    # trace and any internal identifiers stay in the log.
                    logger.exception(
                        "playthrough action failed", exc_info=value
                        if isinstance(value, BaseException) else None
                    )
                    yield _sse("error", {"message": _player_facing_error(value)})
                    return
                if kind == "narrative":
                    streamed = True
                    yield _sse(kind, value)
                elif kind == "progress":
                    yield _sse(kind, value)
                else:
                    result = value
        finally:
            await task
        if result is None:
            return
        payload = result.model_dump(mode="json")
        narrative = payload.pop("narrative", "")
        if not streamed:
            for index in range(0, len(narrative), 24):
                yield _sse("narrative", {"delta": narrative[index : index + 24]})
        yield _sse("state", payload)
        yield _sse("done", {"turn_id": result.turn_id})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
        background=BackgroundTask(lock_context.__aexit__, None, None, None),
    )

"""Recovery capsule construction and the atomic canonical commit boundary."""

from __future__ import annotations

from typing import Any

from engine.actions.schema import ActionOutcome
from engine.core.logging import get_logger
from engine.core.models import GameSession
from engine.core.mutations import ChangeSet
from engine.core.ports import UnitOfWork
from engine.orchestrator.turn import TurnStatus, TurnTrace

logger = get_logger("canonical_commit")


def recovery_capsule(
    *,
    player_action: str,
    outcome: ActionOutcome,
    change_set: ChangeSet,
    before_facts: dict[str, Any],
    npc_lines: list[str],
    world_lines: list[str],
    recent_narrative: str,
    parsed_degraded: bool,
    rejected: dict[str, Any] | None,
    trace: TurnTrace,
    debug_requested: bool,
    narrative_max_chars: int,
    memory_required: bool,
) -> dict[str, Any]:
    """Build all data needed to resume presentation after a durable commit."""
    return {
        "player_action": player_action,
        "outcome": outcome.model_dump(mode="json"),
        "change_set": change_set.model_dump(mode="json"),
        "before_facts": before_facts,
        "npc_lines": npc_lines,
        "world_lines": world_lines,
        "recent_narrative": recent_narrative,
        "parsed_degraded": parsed_degraded,
        "rejected": rejected,
        "trace": trace.as_dict(),
        "debug_requested": debug_requested,
        "narrative_max_chars": narrative_max_chars,
        "memory_projection": {
            "status": "PENDING" if memory_required else "NOT_REQUIRED",
            "attempts": 0,
        },
    }


async def commit_canonical_turn(
    uow: UnitOfWork,
    *,
    session: GameSession,
    turn_id: str,
    turn_number: int,
    player_input: str,
    idempotency_key: str | None,
    world_minute_before: int,
    world_minute_after: int,
    change_set: ChangeSet,
    capsule: dict[str, Any],
) -> None:
    """Commit world mutations, session progress and recovery row atomically."""
    try:
        await uow.apply(change_set)
        session.turn_number = turn_number
        await uow.sessions.save(session)
        await uow.turns.record(
            {
                "id": turn_id,
                "session_id": session.id,
                "turn_number": turn_number,
                "player_input": player_input,
                "idempotency_key": idempotency_key or turn_id,
                "status": str(TurnStatus.CANONICAL_COMMITTED),
                "world_minute_before": world_minute_before,
                "world_minute_after": world_minute_after,
                "canonical_payload": capsule,
                "last_error": {},
                "result": {},
            }
        )
        await uow.commit()
    except Exception as exc:
        await uow.rollback()
        logger.error("commit failed, turn rolled back: %s", exc)
        raise

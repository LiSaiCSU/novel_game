"""Deterministic, content-defined ending evaluation.

Endings are ordinary bounded expressions over canonical state. The LLM may
describe an epilogue, but it never decides which ending exists or is eligible.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict

from engine.contentpack.declarative import RuleLanguageError, evaluate
from engine.contentpack.schema_v2 import EndingDefinition
from engine.core.models import Relationship
from engine.core.ports import UnitOfWork
from engine.world.state_view import WorldStateView


class EndingEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    type: str
    lead: str | None
    available: bool
    requires_consent: bool
    hidden_until_available: bool
    priority: int
    epilogue: str


async def build_ending_context(
    uow: UnitOfWork,
    state: WorldStateView,
    endings: list[EndingDefinition],
) -> dict[str, Any]:
    """Expose only stable, non-secret canonical fields to ending formulas."""
    characters = {
        character.key: character
        for character in await uow.characters.list_for_world(state.world.id)
    }
    relationship_context: dict[str, dict[str, Any]] = {}
    for lead_key in sorted({ending.lead for ending in endings if ending.lead}):
        lead = characters.get(str(lead_key))
        relationship = None
        if lead is not None:
            # NPC -> player is authoritative for NPC affection and trust. A
            # creator-authored player -> NPC row remains a compatibility fallback.
            relationship = await uow.relationships.get(lead.id, state.player.id)
            relationship = relationship or await uow.relationships.get(state.player.id, lead.id)
        relationship_context[str(lead_key)] = _relationship_view(relationship)

    consent = {
        str(key): str(value)
        for key, value in (state.player.properties.get("romance_consent", {}) or {}).items()
    }
    for lead_key in relationship_context:
        consent.setdefault(lead_key, "undecided")

    return {
        "world": {
            "minute": state.world.current_minute,
            "tension": state.world.narrative_tension,
        },
        "player": {
            "attributes": deepcopy(state.player.attributes),
            "resources": deepcopy(state.player.resources),
            "progressions": deepcopy(state.player.progressions),
            "properties": deepcopy(state.player.properties),
        },
        "relationships": relationship_context,
        "consent": consent,
        "quests": {
            quest.key: {
                "status": str(quest.status),
                "assignee": quest.assignee_character_key,
            }
            for quest in state.active_quests
        },
        "threads": {
            thread.key: {"status": str(thread.status), "stage": thread.stage}
            for thread in state.plot_threads
        },
    }


def evaluate_endings(
    endings: list[EndingDefinition], context: dict[str, Any]
) -> list[EndingEvaluation]:
    rows: list[EndingEvaluation] = []
    for ending in endings:
        try:
            available = bool(evaluate(ending.condition, context))
        except (RuleLanguageError, TypeError, ValueError, ZeroDivisionError):
            # Missing or incompatible runtime data locks an ending. It must
            # never accidentally unlock because an author path was malformed.
            available = False
        rows.append(
            EndingEvaluation(
                key=ending.key,
                title=ending.title,
                type=ending.type,
                lead=ending.lead,
                available=available,
                requires_consent=ending.requires_consent,
                hidden_until_available=ending.hidden_until_available,
                priority=ending.priority,
                epilogue=ending.epilogue,
            )
        )
    return sorted(rows, key=lambda row: (-row.priority, row.key))


def _relationship_view(relationship: Relationship | None) -> dict[str, Any]:
    if relationship is None:
        return {
            "affection": 0,
            "trust": 0,
            "respect": 0,
            "fear": 0,
            "hatred": 0,
            "suspicion": 0,
            "dependency": 0,
            "familiarity": 0,
            "boundaries": 50,
            "tags": [],
        }
    return {**relationship.as_dict(), "tags": list(relationship.tags)}

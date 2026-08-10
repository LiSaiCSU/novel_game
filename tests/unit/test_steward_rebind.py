"""Rebinding an intent after the steward has spoken.

The steward runs precisely because the first binding failed, so its reading
wins. The one thing it is not trusted with is physics: "go and talk to the
herbalist" comes back as a single TALK often enough that the trip has to be
the engine's decision, not the model's.
"""

from __future__ import annotations

import pytest

from engine.actions.intent_parser import IntentParser, ParsedIntent
from engine.actions.schema import PlayerIntent
from engine.core.types import ActionType
from engine.world.state_view import WorldStateView
from engine.world.steward import StewardResult

pytestmark = pytest.mark.anyio


def _parsed(state: WorldStateView, text: str, **kwargs) -> ParsedIntent:
    intent = PlayerIntent(actor_id=state.player.id, raw_text=text, **kwargs)
    return ParsedIntent(
        intent=intent,
        action=None,  # type: ignore[arg-type] - rebind never reads it
        plan=None,  # type: ignore[arg-type]
        degraded=False,
    )


async def test_reaching_someone_elsewhere_becomes_a_journey(
    pack, context_builder, state: WorldStateView, uow
) -> None:
    everyone = await uow.characters.list_for_world(state.world.id)
    absent = next(
        c
        for c in everyone
        if c.alive and not state.is_present(c.id) and c.location_key
    )
    parser = IntentParser(pack, context_builder)

    rebound = parser.rebind(
        state,
        _parsed(state, "我去找他聊聊", action_type=ActionType.CONVERSATION),
        StewardResult(
            action_type=ActionType.TALK,
            target_id=absent.id,
            target_key=absent.key,
            location_key=absent.location_key,
        ),
    )

    destination = state.graph.by_key(absent.location_key)
    assert destination is not None
    assert rebound.action.action_type is ActionType.MOVE
    assert rebound.action.target_location_id == destination.id
    # The absent target is dropped rather than left to fail as "not here".
    assert rebound.action.target_id is None


async def test_someone_standing_right_here_is_simply_talked_to(
    pack, context_builder, state: WorldStateView
) -> None:
    if not state.present_characters:
        pytest.skip("nobody is in the starting scene")
    here = state.present_characters[0]
    parser = IntentParser(pack, context_builder)

    rebound = parser.rebind(
        state,
        _parsed(state, "我找他说几句"),
        StewardResult(
            action_type=ActionType.TALK, target_id=here.id, target_key=here.key
        ),
    )

    assert rebound.action.action_type is ActionType.TALK
    assert rebound.action.target_id == here.id


async def test_the_stewards_reading_replaces_the_first_guess(
    pack, context_builder, state: WorldStateView
) -> None:
    """It decided last and knew most, so it is not merely a tie-breaker."""
    parser = IntentParser(pack, context_builder)
    somewhere = next(
        loc for loc in state.graph.all() if loc.key != state.location_key()
    )

    rebound = parser.rebind(
        state,
        _parsed(state, "我去那边看看", action_type=ActionType.OBSERVE),
        StewardResult(action_type=ActionType.MOVE, location_key=somewhere.key),
    )

    assert rebound.action.action_type is ActionType.MOVE
    assert rebound.action.target_location_id == somewhere.id

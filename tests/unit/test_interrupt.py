"""What counts as a moment only the player can answer.

This is the rule that decides how the game feels. Too eager and the player is
back to typing every sentence; too reluctant and the story runs past the thing
they wanted to react to. Both failure modes are regressions, so both are tested.
"""

from __future__ import annotations

import pytest

from engine.actions.schema import ActionOutcome
from engine.core import mutations as mut
from engine.core.models import Event
from engine.core.mutations import ChangeSet
from engine.core.types import ActionType, CharacterType
from engine.orchestrator.interrupt import InterruptDetector, InterruptReason
from engine.world.state_view import WorldStateView

pytestmark = pytest.mark.anyio


@pytest.fixture
def detector(pack) -> InterruptDetector:
    return InterruptDetector(pack)


def _quiet_outcome() -> ActionOutcome:
    return ActionOutcome(
        action_type=ActionType.MOVE, success=True, summary_key="MOVE", importance=0.05
    )


def _npc_record(npc_key: str, **decision) -> dict:
    body = {
        "action_type": decision.pop("action_type", "WAIT"),
        "target": decision.pop("target", None),
    }
    return {"npc": npc_key, "decision": {"decision": body, **decision}}


# ---------------------------------------------------------------- keeps going
async def test_a_quiet_step_does_not_stop_the_story(
    detector: InterruptDetector, state: WorldStateView
) -> None:
    assert (
        detector.detect(
            state,
            outcome=_quiet_outcome(),
            change_set=ChangeSet(),
            npc_decisions=[],
            present=state.present_characters,
            health_before=state.player.health,
        )
        is None
    )


async def test_background_chatter_does_not_stop_the_story(
    detector: InterruptDetector, state: WorldStateView
) -> None:
    """Minor characters talking among themselves is scenery, not a question."""
    minor = next(
        (
            c
            for c in state.present_characters
            if c.character_type is not CharacterType.MAJOR_NPC
        ),
        None,
    )
    if minor is None:
        pytest.skip("no minor character in the starting scene")

    result = detector.detect(
        state,
        outcome=_quiet_outcome(),
        change_set=ChangeSet(),
        npc_decisions=[_npc_record(minor.key, spoken_line="今天天气不错。")],
        present=state.present_characters,
        health_before=state.player.health,
    )
    assert result is None


# ---------------------------------------------------------------- hands back
async def test_a_major_character_speaking_hands_control_back(
    detector: InterruptDetector, state: WorldStateView
) -> None:
    major = next(
        (
            c
            for c in state.present_characters
            if c.character_type is CharacterType.MAJOR_NPC
        ),
        None,
    )
    if major is None:
        pytest.skip("no major character in the starting scene")

    result = detector.detect(
        state,
        outcome=_quiet_outcome(),
        change_set=ChangeSet(),
        npc_decisions=[_npc_record(major.key, spoken_line="你留步。")],
        present=state.present_characters,
        health_before=state.player.health,
    )
    assert result is not None
    assert result.reason is InterruptReason.ADDRESSED
    assert result.involves == [major.display_name]
    assert result.dramatic


async def test_being_attacked_hands_control_back(
    detector: InterruptDetector, state: WorldStateView
) -> None:
    if not state.present_characters:
        pytest.skip("nobody is in the starting scene")
    attacker = state.present_characters[0]

    result = detector.detect(
        state,
        outcome=_quiet_outcome(),
        change_set=ChangeSet(),
        npc_decisions=[
            _npc_record(attacker.key, action_type="ATTACK", target=state.player.key)
        ],
        present=state.present_characters,
        health_before=state.player.health,
    )
    assert result is not None and result.reason is InterruptReason.DANGER


async def test_losing_blood_hands_control_back(
    detector: InterruptDetector, state: WorldStateView
) -> None:
    result = detector.detect(
        state,
        outcome=_quiet_outcome(),
        change_set=ChangeSet(),
        npc_decisions=[],
        present=state.present_characters,
        health_before=state.player.health + state.player.max_health,
    )
    assert result is not None and result.reason is InterruptReason.DANGER


async def test_an_offer_hands_control_back(
    detector: InterruptDetector, state: WorldStateView
) -> None:
    change_set = ChangeSet()
    change_set.add(mut.quest_status("quest-1", "unknown", "offered", reason="test"))

    result = detector.detect(
        state,
        outcome=_quiet_outcome(),
        change_set=change_set,
        npc_decisions=[],
        present=state.present_characters,
        health_before=state.player.health,
    )
    assert result is not None and result.reason is InterruptReason.OFFER


async def test_a_death_hands_control_back(
    detector: InterruptDetector, state: WorldStateView
) -> None:
    if not state.present_characters:
        pytest.skip("nobody is in the starting scene")
    victim = state.present_characters[0]
    change_set = ChangeSet()
    change_set.add(mut.character_death(victim.id, reason="test"))

    result = detector.detect(
        state,
        outcome=_quiet_outcome(),
        change_set=change_set,
        npc_decisions=[],
        present=state.present_characters,
        health_before=state.player.health,
    )
    assert result is not None and result.reason is InterruptReason.DEATH


async def test_an_important_event_hands_control_back(
    detector: InterruptDetector, state: WorldStateView
) -> None:
    change_set = ChangeSet()
    change_set.add_event(
        Event(world_id=state.world.id, event_type="DISCOVERY", importance=0.9)
    )

    result = detector.detect(
        state,
        outcome=_quiet_outcome(),
        change_set=change_set,
        npc_decisions=[],
        present=state.present_characters,
        health_before=state.player.health,
    )
    assert result is not None and result.reason is InterruptReason.MAJOR_EVENT


async def test_the_narrator_gets_a_vote_but_only_the_last_one(
    detector: InterruptDetector, state: WorldStateView
) -> None:
    """A scene that ended on a question is a reason to stop - the weakest one."""
    result = detector.detect(
        state,
        outcome=_quiet_outcome(),
        change_set=ChangeSet(),
        npc_decisions=[],
        present=state.present_characters,
        health_before=state.player.health,
        scene_question=True,
    )
    assert result is not None
    assert result.reason is InterruptReason.SCENE_QUESTION
    assert not result.dramatic

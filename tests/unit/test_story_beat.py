"""Scenes and beats: the game reads like a novel, not a command prompt.

The narrator plays out everything that does not need a decision and raises a
beat when something does. ``继续`` is the other half of that deal - the player
can let the character act on their own until the story needs them again.
"""

from __future__ import annotations

import pytest

from engine.actions.autopilot import Autopilot
from engine.core.types import ActionType
from engine.llm.providers import NullProvider
from engine.narrative.renderer import BEAT_MARKER, split_beat
from engine.orchestrator.factory import build_orchestrator
from engine.orchestrator.turn import Choice, StoryBeat
from engine.world.state_view import WorldStateView

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------- beat parsing
def test_prose_and_beat_are_separated() -> None:
    raw = (
        "韩墨把饼掰成两半，没有抬头。\n\n"
        f"{BEAT_MARKER}\n"
        '{"needs_player": true, "question": "他等着你开口",'
        ' "options": ["顺着他的话问下去", "转身走开"]}'
    )
    prose, beat = split_beat(raw)

    assert prose == "韩墨把饼掰成两半，没有抬头。"
    assert BEAT_MARKER not in prose
    assert beat is not None
    assert beat.needs_player is True
    assert beat.question == "他等着你开口"
    assert [o.label for o in beat.options] == ["顺着他的话问下去", "转身走开"]


def test_a_quiet_turn_does_not_demand_a_decision() -> None:
    raw = f"你收功时天已经亮透了。\n\n{BEAT_MARKER}\n" '{"needs_player": false}'
    prose, beat = split_beat(raw)

    assert prose
    assert beat is not None and beat.needs_player is False
    assert beat.options == []


def test_a_missing_beat_block_still_yields_the_scene() -> None:
    """The prose is the product; the beat is a bonus, never a failure mode."""
    prose, beat = split_beat("雨下了一夜。")
    assert prose == "雨下了一夜。"
    assert beat is None


def test_a_malformed_beat_block_does_not_lose_the_scene() -> None:
    prose, beat = split_beat(f"雨下了一夜。\n{BEAT_MARKER}\n{{not json at all")
    assert prose == "雨下了一夜。"
    assert beat is None


def test_beat_options_are_capped_and_trimmed() -> None:
    raw = (
        f"x\n{BEAT_MARKER}\n"
        '{"options": ["a", "b", "c", "d", "e", {"label": "", "hint": "空的"}]}'
    )
    _, beat = split_beat(raw)
    assert beat is not None
    assert [o.label for o in beat.options] == ["a", "b", "c", "d"]


def test_beat_option_objects_keep_contextual_hints() -> None:
    raw = (
        f"他把账本推到你面前。\n{BEAT_MARKER}\n"
        '{"question":"朝仓律等着你回应","options":['
        '{"label":"我问朝仓律：这笔钱是谁要求隐瞒的？",'
        '"hint":"承接刚出现的账本线索"}]}'
    )
    _, beat = split_beat(raw)

    assert beat is not None
    assert beat.options[0].label == "我问朝仓律：这笔钱是谁要求隐瞒的？"
    assert beat.options[0].hint == "承接刚出现的账本线索"


def test_latest_story_beat_replaces_generic_location_choices(pack, state) -> None:
    orchestrator = build_orchestrator(pack=pack, provider=NullProvider())
    beat = StoryBeat(
        question="他在等你的答案",
        options=[Choice(label="我直接回答他刚才的问题", hint="承接本章最后一句")],
    )

    choices = orchestrator._recommendations(state, beat, None)  # type: ignore[arg-type]

    assert choices == beat.options


# ---------------------------------------------------------------- continue
def test_continue_is_recognised_from_the_content_pack(pack) -> None:
    orchestrator = build_orchestrator(pack=pack, provider=NullProvider())
    assert orchestrator._is_continue("继续")
    assert orchestrator._is_continue("  继续  ")
    # A sentence that merely contains the word is a real action, not autopilot.
    assert not orchestrator._is_continue("我继续追问他昨夜去了哪里")
    assert not orchestrator._is_continue("")


async def test_autopilot_still_acts_when_no_model_is_available(
    pack, state: WorldStateView
) -> None:
    """Degrading means a quieter turn, never a turn that does nothing."""
    autopilot = Autopilot(pack)
    intent, reason = await autopilot.choose(state)

    assert not autopilot.usable()
    assert intent.action_type is ActionType.CULTIVATE
    assert intent.actor_id == state.player.id
    assert reason == ""


async def test_autopilot_never_spends_a_turn_on_the_impossible(
    pack, state: WorldStateView
) -> None:
    """A refusal the player chose is drama; one the autopilot walked into is waste."""
    from engine.actions.autopilot import AutopilotChoice

    autopilot = Autopilot(pack)
    unlearned = AutopilotChoice(
        action_type=ActionType.USE_SKILL, skill_key="a_skill_never_learned"
    )
    assert (
        autopilot._keep_it_possible(state, unlearned).action_type
        is ActionType.CULTIVATE
    )

    missing = AutopilotChoice(action_type=ActionType.USE_ITEM, item_key="not_owned")
    assert autopilot._keep_it_possible(state, missing).action_type is ActionType.OBSERVE

    known = state.known_skills[0].skill_key if state.known_skills else None
    if known:
        kept = AutopilotChoice(action_type=ActionType.USE_SKILL, skill_key=known)
        assert (
            autopilot._keep_it_possible(state, kept).action_type
            is ActionType.USE_SKILL
        )


async def test_an_unreadable_line_offers_a_way_forward_instead_of_an_error_code(
    pack, uow, bundle
) -> None:
    from engine.orchestrator.turn import TurnRequest

    orchestrator = build_orchestrator(pack=pack, provider=NullProvider())
    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=bundle.session.id, text="唔……")
    )

    assert result.rejected is None
    assert result.narrative
    assert result.choices

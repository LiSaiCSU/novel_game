"""Deterministic intent parsing (DECISIONS D-007).

Test A of the V1 goals - "can the system understand what the player said?" -
must hold at a basic level even with no model available.
"""

from __future__ import annotations

import pytest

from engine.actions.fallback_parser import FallbackIntentParser
from engine.contentpack.pack import ContentPack
from engine.core.types import ActionType, RequestSize
from engine.world.state_view import WorldStateView


@pytest.fixture
def parser(pack: ContentPack) -> FallbackIntentParser:
    return FallbackIntentParser(pack)


def test_query_inputs_never_touch_the_world(parser, state: WorldStateView) -> None:
    assert parser.parse("看看我的背包", state).action_type is ActionType.QUERY_INVENTORY
    assert parser.parse("我的状态如何", state).action_type is ActionType.QUERY_STATUS
    assert parser.parse("我认识谁", state).action_type is ActionType.QUERY_RELATIONSHIPS
    assert parser.parse("我的任务", state).action_type is ActionType.QUERY_QUESTS


def test_fallback_never_silently_discards_a_second_action(parser, state) -> None:
    intent = parser.parse("我先环顾四周，然后休息一会儿", state)

    assert intent.action_type is ActionType.CUSTOM
    assert intent.ambiguity == "multi_action_requires_stepwise_input"
    # Flagged, but not a dead end: keyword parsing giving up is the engine's
    # problem to solve downstream, never a turn the player loses.
    assert not intent.needs_clarification()


def test_cultivate_and_duration(parser, state: WorldStateView) -> None:
    intent = parser.parse("我打坐修炼一个时辰", state)
    assert intent.action_type is ActionType.CULTIVATE
    assert intent.duration_minutes == 120


def test_numeric_duration(parser, state: WorldStateView) -> None:
    intent = parser.parse("闭关修炼30日", state)
    assert intent.action_type is ActionType.CULTIVATE
    assert intent.duration_minutes == 30 * 1440


def test_decade_duration_is_parsed_without_per_tick_expansion(
    parser, state: WorldStateView
) -> None:
    intent = parser.parse("我闭关修炼三十年", state)
    assert intent.action_type is ActionType.CULTIVATE
    assert intent.duration_minutes == 30 * state.clock.minutes_per_year


def test_movement_resolves_a_named_location(parser, state: WorldStateView, pack: ContentPack) -> None:
    somewhere = next(
        loc for loc in state.graph.all() if loc.key != state.location_key() and loc.name
    )
    intent = parser.parse(f"我去{somewhere.name}", state)
    assert intent.action_type is ActionType.MOVE
    assert intent.location_key == somewhere.key


def test_movement_without_a_destination_goes_to_the_steward(
    parser, state: WorldStateView
) -> None:
    intent = parser.parse("我要出发", state)
    assert intent.ambiguity == "move_target_unknown"
    # The line is handed on for interpretation rather than bounced back.
    assert intent.unresolved_reference == ["我要出发"]
    assert not intent.needs_clarification()


def test_conversation_target_is_matched_by_name(parser, state: WorldStateView) -> None:
    if not state.present_characters:
        pytest.skip("nobody is in the starting scene")
    npc = state.present_characters[0]
    intent = parser.parse(f"我找{npc.name}聊聊", state)
    assert intent.action_type in (ActionType.TALK, ActionType.CONVERSATION)
    assert intent.target_id == npc.id


def test_deception_is_recorded_as_a_method_not_an_outcome(parser, state: WorldStateView) -> None:
    if not state.present_characters:
        pytest.skip("nobody is in the starting scene")
    npc = state.present_characters[0]
    intent = parser.parse(f"我假装喝醉，去问{npc.name}打听消息", state)
    assert intent.method in ("deceive", "indirect_questioning")
    # the parser decides nothing about whether the deception works
    assert "success" not in intent.model_dump()


def test_extreme_request_is_sized(parser, state: WorldStateView) -> None:
    if not state.present_characters:
        pytest.skip("nobody is in the starting scene")
    npc = state.present_characters[0]
    intent = parser.parse(f"{npc.name}，把你的毕生积蓄送给我", state)
    assert intent.request_size is RequestSize.EXTREME


def test_unparseable_input_asks_for_clarification(parser, state: WorldStateView) -> None:
    intent = parser.parse("嗯……", state)
    assert intent.action_type is ActionType.CUSTOM
    assert intent.confidence < 0.45 or intent.ambiguity is not None


def test_empty_input_is_handled(parser, state: WorldStateView) -> None:
    intent = parser.parse("   ", state)
    assert intent.needs_clarification()
    assert intent.confidence == 0.0


def test_raw_text_is_always_preserved(parser, state: WorldStateView) -> None:
    text = "我沿着院墙走了一圈，看看有没有人在夜里进出"
    assert parser.parse(text, state).raw_text == text


def test_attack_is_understood(parser, state: WorldStateView) -> None:
    if not state.present_characters:
        pytest.skip("nobody is in the starting scene")
    npc = state.present_characters[0]
    intent = parser.parse(f"我一掌拍向{npc.name}", state)
    assert intent.action_type is ActionType.ATTACK
    assert intent.target_id == npc.id

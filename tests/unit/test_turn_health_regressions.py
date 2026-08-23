"""Regressions for failures that only showed up in a real, model-backed game.

Every case here was found by playing the game against a live provider rather
than by reading the code, and every one of them was invisible to the existing
suite because the deterministic path never reached it: the budget guard only
bites after several turns, the memory projection only runs once something
memorable happens, and the plot steward only runs when a model is configured.
"""

from __future__ import annotations

import json

import pytest

from engine.actions.intent_parser import DEFERRABLE_ACTIONS, IntentParser, ParsedIntent
from engine.actions.schema import PlayerIntent
from engine.core.types import ActionType
from engine.llm.budget import BudgetedProvider
from engine.llm.provider import LLMMessage, LLMRequest, LLMResponse, LLMUsage
from engine.narrative.renderer import split_beat
from engine.narrative.style import (
    NarrativeStyle,
    drop_unfinished_tail,
    quotations_balanced,
)
from engine.world.state_view import WorldStateView
from engine.world.steward import StewardResult

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# The inference budget
# ---------------------------------------------------------------------------
class _Provider:
    name = "fake"
    available = True

    def __init__(self) -> None:
        self.calls = 0

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            text="ok",
            model=request.model,
            provider=self.name,
            usage=LLMUsage(prompt_tokens=400, completion_tokens=400),
        )


def _request() -> LLMRequest:
    return LLMRequest(
        model="m",
        messages=[LLMMessage(role="user", content="x" * 400)],
        max_output_tokens=200,
    )


async def test_the_turn_budget_is_spent_per_turn_not_per_process() -> None:
    """A cap that never resets is a cap on the whole session.

    ``_settle`` replaces each reservation with real usage, so the counter only
    grows.  Without a reset the guard eventually refused every call - and
    because the chapter is written last, the refused call was the prose the
    player reads.
    """
    provider = BudgetedProvider(_Provider(), token_limit=1500)

    for _ in range(3):
        provider.begin_turn()
        await provider.generate_text(_request())

    provider.begin_turn()
    assert (await provider.generate_text(_request())).text == "ok"


async def test_one_turn_still_cannot_exceed_its_own_budget() -> None:
    provider = BudgetedProvider(_Provider(), token_limit=1500)
    provider.begin_turn()
    await provider.generate_text(_request())
    with pytest.raises(Exception, match="budget exhausted"):
        for _ in range(6):
            await provider.generate_text(_request())


# ---------------------------------------------------------------------------
# Prose that ends where it means to
# ---------------------------------------------------------------------------
def test_a_truncated_scene_ends_on_its_last_finished_sentence() -> None:
    cut = "他把门推开。“你来晚了。”她说。“东西在哪"
    assert drop_unfinished_tail(cut) == "他把门推开。“你来晚了。”她说。"


def test_the_length_ceiling_never_leaves_a_quotation_open() -> None:
    text = "一" * 380 + "。" + "“我告诉你" + "二" * 200
    clipped = NarrativeStyle.enforce_max_chars(text, 400)
    assert len(clipped) <= 400
    assert quotations_balanced(clipped)


# ---------------------------------------------------------------------------
# The narrator's hand-off
# ---------------------------------------------------------------------------
def test_a_beat_block_is_recovered_when_the_model_drops_the_marker() -> None:
    """Losing the marker cost the player every suggestion for that turn."""
    payload = {
        "needs_player": True,
        "question": "他等着你回话。",
        "options": [{"label": "我把残页递过去。", "hint": "摊牌"}],
    }
    prose, beat = split_beat("他站在门口。\n\n" + json.dumps(payload, ensure_ascii=False))

    assert prose == "他站在门口。"
    assert beat is not None
    assert [option.label for option in beat.options] == ["我把残页递过去。"]


def test_ordinary_prose_containing_braces_is_not_mistaken_for_a_beat() -> None:
    prose, beat = split_beat("他说：这里写着 {某个记号}，看不懂。")

    assert beat is None
    assert prose.endswith("看不懂。")


def test_a_trimmed_option_keeps_its_quotation_closed() -> None:
    from engine.narrative.renderer import _option_label

    label = _option_label('我拦住刘叔：“那条狗后来是谁牵走的？你亲眼看见了？还有谁在场？”')

    assert quotations_balanced(label)


# ---------------------------------------------------------------------------
# Reaching for someone who is not here
# ---------------------------------------------------------------------------
def _parsed(state: WorldStateView, text: str, **kwargs) -> ParsedIntent:
    intent = PlayerIntent(actor_id=state.player.id, raw_text=text, **kwargs)
    return ParsedIntent(
        intent=intent,
        action=None,  # type: ignore[arg-type] - rebind never reads it
        plan=None,  # type: ignore[arg-type]
        degraded=False,
    )


async def test_a_conversation_survives_the_trip_it_had_to_take(
    pack, context_builder, state: WorldStateView, uow
) -> None:
    """The walk is half the request; the other half used to be discarded."""
    everyone = await uow.characters.list_for_world(state.world.id)
    absent = next(c for c in everyone if c.alive and not state.is_present(c.id) and c.location_key)
    parser = IntentParser(pack, context_builder)
    parsed = _parsed(state, "去找他说话", action_type=ActionType.CONVERSATION)
    steward = StewardResult(target_id=absent.id, target_key=absent.key, location_key=absent.location_key)

    rebound = parser.rebind(state, parsed, steward)

    assert rebound.intent.action_type is ActionType.MOVE
    assert rebound.deferred_intent is not None
    assert rebound.deferred_intent.action_type is ActionType.CONVERSATION
    assert rebound.deferred_intent.target_id == absent.id


async def test_a_plain_journey_defers_nothing(
    pack, context_builder, state: WorldStateView, uow
) -> None:
    everyone = await uow.characters.list_for_world(state.world.id)
    absent = next(c for c in everyone if c.alive and not state.is_present(c.id) and c.location_key)
    parser = IntentParser(pack, context_builder)
    parsed = _parsed(state, "去后山", action_type=ActionType.MOVE)
    steward = StewardResult(target_id=absent.id, target_key=absent.key, location_key=absent.location_key)

    rebound = parser.rebind(state, parsed, steward)

    assert rebound.deferred_intent is None
    assert ActionType.MOVE not in DEFERRABLE_ACTIONS


async def test_a_destination_the_player_named_is_not_overruled(
    pack, context_builder, state: WorldStateView, uow
) -> None:
    """Recognising a person also volunteers their location; naming a real
    place has to win, or "go to the training ground and talk to her" walks
    to wherever she happens to be standing."""
    everyone = await uow.characters.list_for_world(state.world.id)
    absent = next(
        c
        for c in everyone
        if c.alive
        and not state.is_present(c.id)
        and c.location_key
        and c.location_key != state.location_key()
    )
    named = next(
        loc for loc in state.graph.all() if loc.key not in (absent.location_key, state.location_key())
    )
    parser = IntentParser(pack, context_builder)
    parsed = _parsed(
        state,
        "去那边找她说话",
        action_type=ActionType.CONVERSATION,
        location_key=named.key,
    )
    steward = StewardResult(
        target_id=absent.id, target_key=absent.key, location_key=absent.location_key
    )

    rebound = parser.rebind(state, parsed, steward)

    assert rebound.intent.location_key == named.key


# ---------------------------------------------------------------------------
# The projections that only run once something matters
# ---------------------------------------------------------------------------
def test_the_memory_extractor_asks_for_a_prompt_that_exists(registry) -> None:
    """The file was named after the module, the caller after the role.

    Nothing noticed, because nothing in ordinary play ever cleared the memory
    threshold - and when something finally did, the missing file failed a turn
    that had already been committed, permanently.
    """
    assert registry.get("memory_extractor", "v1").body


def test_saved_worlds_carry_their_visible_pressure() -> None:
    from database.models.orm import StoryClockORM
    from database.saves import _WORLD_TABLES

    assert StoryClockORM in _WORLD_TABLES


def test_a_conversation_with_someone_new_is_worth_remembering(pack) -> None:
    floor = float(pack.rule("memory.min_importance", 0.3))
    weights = pack.rule("memory.conversation_importance", {}) or {}

    assert float(weights["first_meeting"]) >= floor
    assert float(weights["major_npc"]) >= floor


def test_walking_around_does_not_ratchet_the_story_tension(pack) -> None:
    from engine.director.tension import TensionModel

    tension = TensionModel(pack)
    quiet = tension.apply(30.0, days_elapsed=0.0, importance=pack.event_importance("MOVE"))
    loud = tension.apply(30.0, days_elapsed=0.0, importance=1.0)

    assert quiet == 30.0
    assert loud > 30.0

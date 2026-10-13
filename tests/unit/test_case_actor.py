"""Free text in a case: the model may only choose legal moves or speak in character."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.case.actor import _clean_reply, actor_prompt, interpret
from engine.case.engine import CaseEngine, Move, MoveRejected
from engine.case.library import load_cases
from engine.core.config import Settings
from engine.llm.providers import ScriptedProvider
from engine.orchestrator.factory import build_llm_client

CASES_DIR = str(Path(__file__).resolve().parents[2] / "content" / "cases")


@pytest.fixture(scope="module")
def engine() -> CaseEngine:
    return CaseEngine(load_cases(CASES_DIR)["egret_purser"])


def _llm(registry, response: dict):
    settings = Settings(llm_provider="scripted", llm_model="scripted-model")
    return build_llm_client(
        settings, provider=ScriptedProvider({"玩家刚才说": response}), registry=registry
    )


def _state(engine: CaseEngine):
    state = engine.new_state("actor")
    for move in (Move("begin"), Move("examine", "pockets"), Move("talk", "xiaoshun")):
        state = engine.apply(state, move)
    return state


async def test_recognised_option_becomes_that_move(engine, registry) -> None:
    llm = _llm(registry, {"action": "option", "option": "xs_ask_room"})
    move = await interpret(llm, engine, _state(engine), "xiaoshun", "你进去时看见什么了？")
    assert move.kind == "option" and move.target == "xs_ask_room"
    assert move.said == "你进去时看见什么了？"


async def test_recognised_presentation_is_rechecked(engine, registry) -> None:
    state = _state(engine)
    llm = _llm(
        registry, {"action": "present", "statement": "xs_untouched", "evidence": "watch_chain"}
    )
    move = await interpret(llm, engine, state, "xiaoshun", "表链怎么空了？")
    assert (move.kind, move.target, move.evidence) == ("present", "xs_untouched", "watch_chain")
    after = engine.apply(state, move)
    assert "xs_untouched" in after.broken
    assert after.log[next(i for i, e in enumerate(after.log) if e.text == "表链怎么空了？")].kind == "player"


async def test_illegal_pick_falls_back_to_the_reply(engine, registry) -> None:
    llm = _llm(
        registry,
        {"action": "present", "statement": "sb_left", "evidence": "cane", "reply": "（他摇头）不晓得。"},
    )
    move = await interpret(llm, engine, _state(engine), "xiaoshun", "随便问问")
    assert move.kind == "chat" and move.reply == "（他摇头）不晓得。"


async def test_illegal_pick_without_reply_is_rejected(engine, registry) -> None:
    llm = _llm(registry, {"action": "option", "option": "sb_press_cotton"})
    with pytest.raises(MoveRejected):
        await interpret(llm, engine, _state(engine), "xiaoshun", "你说呢")


def test_prompt_holds_only_what_has_been_said(engine, registry) -> None:
    state = _state(engine)
    state = engine.apply(state, Move("talk", "song"))
    prompt = actor_prompt(registry, engine, state, "song", "你好")
    assert engine.case.statement("sb_cards")[1].text in prompt
    for hidden in (
        engine.case.statement("sb_left")[1].text,
        "生丝掉包骗保",
        "contradicted_by",
        "沈墨卿那个死脑筋",
    ):
        assert hidden not in prompt


def test_reply_cleanup_strips_json_debris() -> None:
    assert _clean_reply("说变就变。您说是吧？”}】}") == "说变就变。您说是吧？"
    assert _clean_reply("他说“好”") == "他说“好”"

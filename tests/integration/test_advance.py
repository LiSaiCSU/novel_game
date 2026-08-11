"""A turn is a stretch of story, not a single action.

These tests pin the pacing contract: one player input runs the character
forward through several adjudicated steps, stops at the first thing that needs
a decision, and comes back as one chapter rather than a stack of paragraphs.
"""

from __future__ import annotations

import pytest

from engine.actions.autopilot import AutopilotChoice, AutopilotRun
from engine.core.types import ActionType
from engine.llm.providers import NullProvider
from engine.orchestrator.factory import build_orchestrator
from engine.orchestrator.interrupt import InterruptReason
from engine.orchestrator.turn import TurnRequest, TurnStatus

pytestmark = pytest.mark.integration


@pytest.fixture
def orchestrator(pack, registry):
    return build_orchestrator(pack=pack, registry=registry, provider=NullProvider())


class _ScriptedAutopilot:
    """Stands in for the planner so pacing can be tested without a model."""

    def __init__(self, orchestrator, steps: list[AutopilotChoice]) -> None:
        self._real = orchestrator.d.autopilot
        self._steps = steps
        self.calls = 0
        self.player_input = ""

    def usable(self) -> bool:
        return True

    async def plan_run(
        self,
        state,
        *,
        steps: int,
        recent_narrative: str = "",
        player_input: str = "",
        player_did: str = "",
    ):
        self.calls += 1
        self.player_input = player_input
        run = AutopilotRun(intent="把手边的事办完", steps=self._steps[:steps])
        return [
            self._real._to_intent(state, self._real._keep_it_possible(state, choice))
            for choice in run.steps
        ], run.intent


async def test_one_input_runs_several_steps_and_returns_one_chapter(
    orchestrator, uow, bundle
) -> None:
    orchestrator.d.autopilot = _ScriptedAutopilot(
        orchestrator,
        [
            AutopilotChoice(action_type=ActionType.OBSERVE, reason="看看四周"),
            AutopilotChoice(action_type=ActionType.WAIT, reason="等一等"),
            AutopilotChoice(action_type=ActionType.OBSERVE, reason="再看一眼"),
        ],
    )

    result = await orchestrator.advance(
        uow, TurnRequest(session_id=bundle.session.id, text="我打坐修炼一个时辰")
    )

    # The player acted once; the character kept going.
    assert result.steps > 1
    assert result.status is TurnStatus.COMPLETED
    assert result.narrative
    assert result.interrupt is not None
    # One planning call for the whole run, not one per step.
    assert orchestrator.d.autopilot.calls == 1


async def test_the_run_continues_what_the_player_asked_for(
    orchestrator, uow, bundle
) -> None:
    """The planner must be told what the player said, or it hijacks the story.

    Reported symptom: the player typed "过去看看是干什么的" about a notice that
    had just been announced, and the run went off to interview someone else
    about an unrelated theft - because the planner only ever saw the
    character's standing goals.
    """
    orchestrator.d.autopilot = _ScriptedAutopilot(
        orchestrator,
        [AutopilotChoice(action_type=ActionType.OBSERVE, reason="看看告示")],
    )

    await orchestrator.advance(
        uow,
        TurnRequest(session_id=bundle.session.id, text="过去看看告示写的是什么"),
    )

    assert orchestrator.d.autopilot.player_input == "过去看看告示写的是什么"


async def test_a_bare_continue_leaves_the_planner_to_its_own_judgement(
    orchestrator, uow, bundle
) -> None:
    """Only when the player says nothing do standing goals take over."""
    orchestrator.d.autopilot = _ScriptedAutopilot(
        orchestrator,
        [AutopilotChoice(action_type=ActionType.OBSERVE, reason="看看四周")],
    )

    await orchestrator.advance(
        uow, TurnRequest(session_id=bundle.session.id, text="继续")
    )

    assert orchestrator.d.autopilot.player_input == ""


async def test_a_bare_continue_with_an_idempotency_key_replays_the_same_run(
    orchestrator, uow, bundle
) -> None:
    orchestrator.d.autopilot = _ScriptedAutopilot(
        orchestrator,
        [AutopilotChoice(action_type=ActionType.OBSERVE, reason="看看四周")],
    )
    request = TurnRequest(
        session_id=bundle.session.id,
        text="继续",
        idempotency_key="continue-run-key",
        narrative_max_chars=1200,
    )

    first = await orchestrator.advance(uow, request)
    second = await orchestrator.advance(uow, request)

    assert second.turn_id == first.turn_id
    assert second.narrative == first.narrative


async def test_the_run_is_recorded_as_one_chapter_not_one_segment_per_step(
    orchestrator, uow, bundle
) -> None:
    orchestrator.d.autopilot = _ScriptedAutopilot(
        orchestrator,
        [AutopilotChoice(action_type=ActionType.OBSERVE, reason="看看四周")] * 3,
    )

    await orchestrator.advance(
        uow, TurnRequest(session_id=bundle.session.id, text="我环顾四周")
    )

    segments = await uow.turns.list_narrative(bundle.session.id, limit=20)
    assert len(segments) == 1
    assert segments[0].kind == "chapter"


async def test_every_step_of_a_run_is_a_committed_turn(
    orchestrator, uow, bundle, store
) -> None:
    """Batching the prose must not batch away the audit trail."""
    orchestrator.d.autopilot = _ScriptedAutopilot(
        orchestrator,
        [AutopilotChoice(action_type=ActionType.OBSERVE, reason="看看四周")] * 2,
    )

    result = await orchestrator.advance(
        uow, TurnRequest(session_id=bundle.session.id, text="我环顾四周")
    )

    turns = await uow.turns.list_for_session(bundle.session.id, limit=50)
    assert len(turns) == result.steps
    assert all(t["status"] == str(TurnStatus.COMPLETED) for t in turns)
    assert all(
        (t.get("canonical_payload") or {}).get("memory_projection", {}).get("status")
        in {"COMPLETED", "NOT_REQUIRED"}
        for t in turns
    )


async def test_the_run_stops_at_the_first_thing_that_needs_the_player(
    orchestrator, uow, bundle, store
) -> None:
    """A drawn blade ends the run; the remaining planned steps are dropped."""
    player = next(c for c in store.characters.values() if c.key == "player")
    attacker = next(
        c
        for c in store.characters.values()
        if c.location_id == player.location_id and c.id != player.id
    )
    orchestrator.d.autopilot = _ScriptedAutopilot(
        orchestrator,
        [
            AutopilotChoice(
                action_type=ActionType.ATTACK,
                target_key=attacker.key,
                reason="先下手为强",
            ),
            AutopilotChoice(action_type=ActionType.OBSERVE, reason="不该走到这一步"),
            AutopilotChoice(action_type=ActionType.OBSERVE, reason="更不该"),
        ],
    )

    result = await orchestrator.advance(
        uow, TurnRequest(session_id=bundle.session.id, text="继续")
    )

    assert result.interrupt is not None
    assert result.interrupt["reason"] in (
        str(InterruptReason.DANGER),
        str(InterruptReason.DEATH),
        str(InterruptReason.MAJOR_EVENT),
        str(InterruptReason.ACTED_UPON),
    )
    # It stopped early rather than playing out the whole plan.
    assert result.steps < 3


async def test_without_a_model_a_turn_stays_a_single_turn(
    orchestrator, uow, bundle
) -> None:
    """The deterministic fallback would just repeat itself, so it does not run."""
    result = await orchestrator.advance(
        uow, TurnRequest(session_id=bundle.session.id, text="我环顾四周")
    )

    assert result.steps == 1
    assert result.narrative


async def test_a_retried_request_replays_instead_of_acting_again(
    orchestrator, uow, bundle, store
) -> None:
    orchestrator.d.autopilot = _ScriptedAutopilot(
        orchestrator,
        [AutopilotChoice(action_type=ActionType.OBSERVE, reason="看看四周")] * 2,
    )
    request = TurnRequest(
        session_id=bundle.session.id, text="我环顾四周", idempotency_key="run-key-1"
    )

    first = await orchestrator.advance(uow, request)
    minute = store.worlds[bundle.world.id].current_minute
    second = await orchestrator.advance(uow, request)

    assert first.turn_id == second.turn_id
    assert first.narrative == second.narrative
    assert store.worlds[bundle.world.id].current_minute == minute


async def test_advance_rejects_reusing_a_key_for_different_input_or_length(
    orchestrator, uow, bundle
) -> None:
    from engine.core.errors import EngineError

    await orchestrator.advance(
        uow,
        TurnRequest(
            session_id=bundle.session.id,
            text="我环顾四周",
            idempotency_key="advance-request-identity",
            narrative_max_chars=1200,
        ),
    )
    with pytest.raises(EngineError, match="different input"):
        await orchestrator.advance(
            uow,
            TurnRequest(
                session_id=bundle.session.id,
                text="我打坐修炼",
                idempotency_key="advance-request-identity",
                narrative_max_chars=1200,
            ),
        )
    with pytest.raises(EngineError, match="different narrative length"):
        await orchestrator.advance(
            uow,
            TurnRequest(
                session_id=bundle.session.id,
                text="我环顾四周",
                idempotency_key="advance-request-identity",
                narrative_max_chars=1800,
            ),
        )


async def test_the_opening_chapter_is_recorded_so_the_first_move_can_answer_it(
    orchestrator, uow, bundle, pack
) -> None:
    """The player's first line is a reply to the opening. It must be on record.

    Reported symptom: the opening ended with a notice being posted, the player
    typed "过去看看是干什么的", and the story went somewhere else entirely -
    because open_session returned the chapter to the client without ever
    writing it down. The engine was resolving a reply to text it had not seen.
    """
    from engine.orchestrator.turn import Choice, StoryBeat
    from engine.world.state_view import build_world_state

    state = await build_world_state(
        uow, pack, bundle.world.id, bundle.session.player_character_id
    )

    async def scripted(_uow, _state):
        from engine.narrative.prologue import PrologueResult

        return PrologueResult(
            text="院门口贴出了赤霞秘境名额的告示。",
            beat=StoryBeat(
                needs_player=True,
                question="告示前围了一圈人，你要过去看看吗",
                options=[Choice(label="去看告示")],
            ),
            goals=["弄清名额细则"],
        )

    orchestrator.d.prologue.write = scripted
    await orchestrator.open_session(uow, bundle.session, state)

    # The chapter is readable as story...
    recent = await orchestrator._recent_narrative(uow, bundle.session.id)
    assert "赤霞秘境名额的告示" in recent
    # ...and its unanswered question is available to the parser...
    pending = await orchestrator._pending_beat(uow, bundle.session.id)
    assert "告示前围了一圈人" in pending
    assert "去看告示" in pending
    # ...but the machine-readable beat never leaks into the prose context.
    assert "needs_player" not in recent

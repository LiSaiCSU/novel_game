"""Orchestrator tests: a complete player turn, end to end (Prompt section 61).

Everything here runs with LLM_PROVIDER=null, so what is being verified is the
world engine itself, not a model's prose.
"""

from __future__ import annotations

import pytest

from engine.core.types import ActionType, ReasonCode
from engine.orchestrator.turn import TurnRequest


async def test_a_turn_produces_narrative_state_and_a_trace(orchestrator, uow, session_id) -> None:
    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="我环顾四周", debug=True)
    )
    assert result.narrative
    assert result.turn_id
    assert result.visible_updates["location"]["name"]
    assert result.debug is not None
    assert result.debug["intent"]["action_type"] == str(ActionType.OBSERVE)
    assert "snapshot" in result.debug["stage_timings"]
    assert result.debug["rng_traces"] is not None


async def test_world_time_advances_with_the_action(orchestrator, uow, session_id, store) -> None:
    world = next(iter(store.worlds.values()))
    before = world.current_minute
    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="我打坐修炼一个时辰")
    )
    after = next(iter(store.worlds.values())).current_minute
    assert after > before
    assert result.state_changes["world_minute"] == [before, after]
    assert result.state_changes["time_label"][0] != result.state_changes["time_label"][1] or after - before < 60


async def test_query_turns_are_free(orchestrator, uow, session_id, store) -> None:
    """Prompt section 6: looking in your own bag is a database read."""
    before = next(iter(store.worlds.values())).current_minute
    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="看看我的背包", debug=True)
    )
    after = next(iter(store.worlds.values())).current_minute
    assert after == before
    assert result.narrative
    assert result.debug["intent"]["action_type"] == str(ActionType.QUERY_INVENTORY)
    assert result.debug["llm_calls"] == []
    assert result.debug["npc_decisions"] == []


async def test_impossible_action_is_refused_and_changes_nothing(
    orchestrator, uow, session_id, store, pack
) -> None:
    """Test B of the V1 goals: can the world say no?"""
    player = next(c for c in store.characters.values() if c.key == "player")
    before_realm = player.realm
    high_skill = next(
        s["name"]
        for s in pack.skills
        if pack.realms.order(str(s["required_realm"])) > pack.realms.order(player.realm)
    )
    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text=f"我施展{high_skill}", debug=True)
    )
    assert result.rejected is not None
    assert result.rejected["reason_code"] in (
        str(ReasonCode.SKILL_NOT_LEARNED),
        str(ReasonCode.REALM_TOO_LOW),
    )
    assert result.narrative
    assert next(c for c in store.characters.values() if c.key == "player").realm == before_realm


async def test_ambiguous_input_asks_instead_of_guessing(orchestrator, uow, session_id, store) -> None:
    before = next(iter(store.worlds.values())).current_minute
    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="唔……")
    )
    assert result.rejected is not None
    assert result.rejected["reason_code"] == str(ReasonCode.AMBIGUOUS_INTENT)
    assert next(iter(store.worlds.values())).current_minute == before


async def test_idempotency_key_replays_rather_than_repeating(
    orchestrator, uow, session_id, store
) -> None:
    request = TurnRequest(
        session_id=session_id, text="我打坐修炼一个时辰", idempotency_key="turn-key-1"
    )
    first = await orchestrator.play_turn(uow, request)
    minute_after_first = next(iter(store.worlds.values())).current_minute
    second = await orchestrator.play_turn(uow, request)
    assert second.turn_id == first.turn_id
    assert next(iter(store.worlds.values())).current_minute == minute_after_first


async def test_events_are_appended_for_every_meaningful_turn(
    orchestrator, uow, session_id, store
) -> None:
    before = len(store.events)
    await orchestrator.play_turn(uow, TurnRequest(session_id=session_id, text="我打坐修炼一个时辰"))
    assert len(store.events) > before
    assert any(e.event_type == "CULTIVATION_SESSION" for e in store.events)


async def test_turn_and_trace_are_persisted(orchestrator, uow, session_id) -> None:
    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="我环顾四周")
    )
    stored = await uow.turns.get(result.turn_id)
    trace = await uow.turns.get_trace(result.turn_id)
    assert stored is not None
    assert stored["player_input"] == "我环顾四周"
    assert trace is not None
    assert trace["stage_timings"]


async def test_cultivating_to_the_cap_then_breaking_through(
    orchestrator, uow, session_id, store
) -> None:
    """The full progression loop, driven only through natural language."""
    player_id = next(c.id for c in store.characters.values() if c.key == "player")
    for _ in range(12):
        await orchestrator.play_turn(
            uow, TurnRequest(session_id=session_id, text="我闭关修炼30日")
        )
        if store.characters[player_id].cultivation_progress >= 0.999:
            break
    player = store.characters[player_id]
    assert player.cultivation_progress >= 0.999, "cultivation should reach the stage cap"

    before = (player.realm, player.realm_stage)
    for _ in range(8):
        await orchestrator.play_turn(uow, TurnRequest(session_id=session_id, text="我尝试突破"))
        refreshed = store.characters[player_id]
        if (refreshed.realm, refreshed.realm_stage) != before:
            break
    after = store.characters[player_id]
    assert any(e.event_type in ("BREAKTHROUGH", "BREAKTHROUGH_FAILED") for e in store.events)
    if (after.realm, after.realm_stage) != before:
        assert after.cultivation_progress == 0.0


async def test_relationship_moves_only_a_little_from_small_talk(
    orchestrator, uow, session_id, store, state
) -> None:
    """Prompt section 14, verified through the whole pipeline."""
    if not state.present_characters:
        pytest.skip("nobody is in the starting scene")
    npc = state.present_characters[0]
    player_id = state.player.id
    for _ in range(3):
        await orchestrator.play_turn(
            uow, TurnRequest(session_id=session_id, text=f"我找{npc.name}随便聊两句")
        )
    rel = store.relationships.get((npc.id, player_id))
    if rel is not None:
        assert abs(rel.trust) <= 10
        assert abs(rel.affection) <= 10


async def test_a_long_seclusion_changes_the_world(orchestrator, uow, session_id, store) -> None:
    """Test F: the places the player left keep moving (Prompt section 72)."""
    factions_before = {f.id: dict(f.resources) for f in store.factions.values()}
    positions_before = {c.id: c.location_id for c in store.characters.values()}

    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="我闭关修炼3年", debug=True)
    )
    assert result.debug["simulation"] is not None
    assert result.debug["simulation"]["minutes"] > 100_000

    factions_after = {f.id: dict(f.resources) for f in store.factions.values()}
    positions_after = {c.id: c.location_id for c in store.characters.values()}
    assert factions_after != factions_before, "factions must drift over three years"
    assert positions_after != positions_before, "NPCs must not stand still for three years"


async def test_offline_quests_get_taken_by_someone_else(
    orchestrator, uow, session_id, store
) -> None:
    """Prompt sections 41-42: refusing a task does not freeze it."""
    offered = [q for q in store.quests.values() if str(q.status) == "offered"]
    assert offered, "content pack should ship offered quests"
    await orchestrator.play_turn(uow, TurnRequest(session_id=session_id, text="我闭关修炼3年"))
    statuses = {str(q.status) for q in store.quests.values()}
    assert statuses & {"taken_by_other", "expired"}, (
        "an ignored, expired task must be resolved by the world"
    )


async def test_dead_npcs_stay_dead_across_turns(orchestrator, uow, session_id, store, state) -> None:
    if not state.present_characters:
        pytest.skip("nobody is in the starting scene")
    victim = state.present_characters[0]
    store.characters[victim.id].alive = False
    store.characters[victim.id].health = 0

    await orchestrator.play_turn(uow, TurnRequest(session_id=session_id, text="我闭关修炼3年"))
    assert not store.characters[victim.id].alive

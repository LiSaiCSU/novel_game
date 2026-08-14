"""Orchestrator tests: a complete player turn, end to end (Prompt section 61).

Everything here runs with LLM_PROVIDER=null, so what is being verified is the
world engine itself, not a model's prose.
"""

from __future__ import annotations

import pytest

from engine.core.types import ActionType, ReasonCode
from engine.orchestrator.turn import TurnRequest, TurnStatus


async def test_a_turn_produces_narrative_state_and_a_trace(orchestrator, uow, session_id) -> None:
    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="我环顾四周", debug=True)
    )
    assert result.narrative
    assert result.turn_id
    assert result.idempotency_key
    assert result.visible_updates["location"]["name"]
    assert result.debug is not None
    assert result.debug["intent"]["action_type"] == str(ActionType.OBSERVE)
    assert "snapshot" in result.debug["stage_timings"]
    assert result.debug["rng_traces"] is not None


async def test_final_trace_includes_post_commit_narrative_call(
    pack, registry, uow, session_id
) -> None:
    from engine.core.config import Settings
    from engine.llm.providers import ScriptedProvider
    from engine.orchestrator.factory import build_orchestrator

    settings = Settings(
        llm_provider="scripted",
        llm_model="",
        intent_model="",
        npc_model="",
        npc_major_model="",
        director_model="",
        steward_model="",
        memory_model="",
        narrative_model="test-writer",
        debug_mode=True,
    )
    scripted = ScriptedProvider(default="你静下心来，按既定方法完成了这次修炼。")
    subject = build_orchestrator(
        settings=settings,
        pack=pack,
        provider=scripted,
        registry=registry,
    )

    result = await subject.play_turn(
        uow,
        TurnRequest(session_id=session_id, text="我打坐修炼一个时辰", debug=True),
    )
    stored_trace = await uow.turns.get_trace(result.turn_id)

    assert result.debug is not None
    assert stored_trace is not None
    assert [call["role"] for call in result.debug["llm_calls"]] == ["narrative"]
    assert [call["role"] for call in stored_trace["llm_calls"]] == ["narrative"]
    assert result.debug["token_usage"]["completion"] > 0


async def test_advance_trace_and_usage_include_the_final_chapter_call(
    pack, registry, uow, session_id
) -> None:
    from engine.core.config import Settings
    from engine.llm.providers import ScriptedProvider
    from engine.orchestrator.factory import build_orchestrator

    settings = Settings(
        llm_provider="scripted",
        llm_model="",
        intent_model="",
        npc_model="",
        npc_major_model="",
        director_model="",
        steward_model="",
        memory_model="",
        narrative_model="test-writer",
        debug_mode=True,
    )
    subject = build_orchestrator(
        settings=settings,
        pack=pack,
        provider=ScriptedProvider(default="你完成了行动，世界安静地向前推进。"),
        registry=registry,
    )

    result = await subject.advance(
        uow,
        TurnRequest(session_id=session_id, text="我打坐修炼一个时辰", debug=True),
    )
    stored_trace = await uow.turns.get_trace(result.turn_id)

    assert result.debug is not None
    assert stored_trace is not None
    assert [call["role"] for call in result.debug["llm_calls"]] == ["narrative"]
    assert [call["role"] for call in stored_trace["llm_calls"]] == ["narrative"]
    assert [record.role for record in subject.d.llm.records] == ["narrative"]


async def test_world_time_advances_with_the_action(orchestrator, uow, session_id, store) -> None:
    world = next(iter(store.worlds.values()))
    before = world.current_minute
    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="我打坐修炼一个时辰")
    )
    after = next(iter(store.worlds.values())).current_minute
    assert after > before
    assert result.state_changes["world_minute"] == [before, after]
    assert (
        result.state_changes["time_label"][0] != result.state_changes["time_label"][1]
        or after - before < 60
    )


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


async def test_unreadable_input_holds_the_scene_without_blaming_the_player(
    orchestrator, uow, session_id, store
) -> None:
    before = next(iter(store.worlds.values())).current_minute
    result = await orchestrator.play_turn(uow, TurnRequest(session_id=session_id, text="唔……"))
    # No error code reaches the player, and the free turn still offers a way on.
    assert result.rejected is None
    assert result.narrative
    assert result.choices
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


async def test_multi_primitive_plan_narrative_retry_never_repeats_any_step(
    orchestrator, uow, state, session_id, store, monkeypatch
) -> None:
    from engine.actions.intent_parser import ParsedIntent
    from engine.actions.schema import Action, ActionPlan, ActionPrimitive, PlayerIntent

    recipient = state.present_characters[0]
    owned = next(row for row in state.inventory if row.quantity > 0)
    give = Action(
        action_type=ActionType.GIVE_ITEM,
        actor_id=state.player.id,
        target_id=recipient.id,
        item_key=owned.item_key,
        quantity=1,
        raw_text="我先把东西给他，然后和他谈谈",
    )
    talk = Action(
        action_type=ActionType.TALK,
        actor_id=state.player.id,
        target_id=recipient.id,
        raw_text=give.raw_text,
        utterance="近来可好？",
    )
    compiled = ActionPlan(
        primitives=[
            ActionPrimitive(primitive_id="give", action=give),
            ActionPrimitive(primitive_id="talk", action=talk),
        ]
    )
    parsed = ParsedIntent(
        intent=PlayerIntent(action_type=ActionType.GIVE_ITEM, raw_text=give.raw_text),
        action=give,
        plan=compiled,
        degraded=False,
    )

    async def parse_plan(*args, **kwargs):
        return parsed

    monkeypatch.setattr(orchestrator.d.intent_parser, "parse", parse_plan)
    original_decide = orchestrator.d.npc_agent.decide
    npc_situations = []

    async def capture_npc_situation(uow, ctx, npc, situation, available_actions, **kwargs):
        npc_situations.append(situation)
        return await original_decide(uow, ctx, npc, situation, available_actions, **kwargs)

    monkeypatch.setattr(orchestrator.d.npc_agent, "decide", capture_npc_situation)
    original_render = orchestrator.d.narrative.render
    narrative_calls = 0

    async def fail_narrative_once(*args, **kwargs):
        nonlocal narrative_calls
        narrative_calls += 1
        if narrative_calls == 1:
            raise RuntimeError("injected plan narrative crash")
        return await original_render(*args, **kwargs)

    monkeypatch.setattr(orchestrator.d.narrative, "render", fail_narrative_once)
    request = TurnRequest(
        session_id=session_id,
        text=give.raw_text,
        idempotency_key="multi-primitive-idempotency",
    )

    first = await orchestrator.play_turn(uow, request)
    minute_after_first = next(iter(store.worlds.values())).current_minute
    events_after_first = len(store.events)
    recipient_quantity = store.inventory[(recipient.id, owned.item_key)].quantity
    first_turn_events = [event for event in store.events if event.turn_id == first.turn_id]
    second = await orchestrator.play_turn(uow, request)

    assert first.status is TurnStatus.NARRATIVE_FAILED
    assert second.status is TurnStatus.COMPLETED
    assert second.turn_id == first.turn_id
    assert next(iter(store.worlds.values())).current_minute == minute_after_first
    assert len(store.events) == events_after_first
    assert store.inventory[(recipient.id, owned.item_key)].quantity == recipient_quantity
    primitive_events = [e for e in first_turn_events if e.payload.get("primitive_id")]
    assert [e.payload["primitive_id"] for e in primitive_events[:2]] == ["give", "talk"]
    assert primitive_events[0].id in primitive_events[1].cause_event_ids
    assert npc_situations
    assert all(situation.player_action is ActionType.TALK for situation in npc_situations)
    assert all(situation.utterance == talk.utterance for situation in npc_situations)
    assert narrative_calls == 2


async def test_narrative_failure_retry_never_reexecutes_canonical_action(
    orchestrator, uow, session_id, store, monkeypatch
) -> None:
    """The crash window after canonical commit must be presentation-only."""
    original_render = orchestrator.d.narrative.render
    calls = 0

    async def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected narrative crash")
        return await original_render(*args, **kwargs)

    monkeypatch.setattr(orchestrator.d.narrative, "render", fail_once)
    request = TurnRequest(
        session_id=session_id,
        text="我打坐修炼一个时辰",
        idempotency_key="narrative-retry-key",
    )

    before = next(iter(store.worlds.values())).current_minute
    first = await orchestrator.play_turn(uow, request)
    after_first = next(iter(store.worlds.values())).current_minute
    events_after_first = len(store.events)
    stored_after_first = await uow.turns.get(first.turn_id)

    assert after_first > before
    assert first.status is TurnStatus.NARRATIVE_FAILED
    assert first.degraded
    assert stored_after_first is not None
    assert stored_after_first["status"] == str(TurnStatus.NARRATIVE_FAILED)

    second = await orchestrator.play_turn(uow, request)
    assert second.turn_id == first.turn_id
    assert second.status is TurnStatus.COMPLETED
    assert next(iter(store.worlds.values())).current_minute == after_first
    assert len(store.events) == events_after_first
    assert calls == 2


async def test_memory_failure_retry_projects_events_without_reexecuting_action(
    orchestrator, uow, session_id, store, monkeypatch
) -> None:
    """A post-commit memory crash must resume from the recovery capsule."""
    from engine.core.errors import EngineError

    original_extract = orchestrator.d.memory.extract
    calls = 0

    async def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected memory projection crash")
        return await original_extract(*args, **kwargs)

    monkeypatch.setattr(orchestrator.d.memory, "extract", fail_once)
    request = TurnRequest(
        session_id=session_id,
        text="我打坐修炼一个时辰",
        idempotency_key="memory-retry-key",
    )
    before = next(iter(store.worlds.values())).current_minute

    with pytest.raises(EngineError, match="memory projection failed after canonical commit"):
        await orchestrator.play_turn(uow, request)

    after_failure = next(iter(store.worlds.values())).current_minute
    events_after_failure = len(store.events)
    failed = await uow.turns.get_by_idempotency_key("memory-retry-key")
    assert failed is not None
    assert failed["status"] == str(TurnStatus.CANONICAL_COMMITTED)
    assert failed["canonical_payload"]["memory_projection"]["status"] == "FAILED"
    assert after_failure > before

    result = await orchestrator.play_turn(uow, request)
    completed = await uow.turns.get(result.turn_id)

    assert result.status is TurnStatus.COMPLETED
    assert next(iter(store.worlds.values())).current_minute == after_failure
    assert len(store.events) == events_after_failure
    assert calls == 2
    assert completed is not None
    assert completed["canonical_payload"]["memory_projection"]["status"] == "COMPLETED"
    assert completed["canonical_payload"]["memory_projection"]["attempts"] == 2


async def test_partial_memory_projection_rolls_back_as_one_transaction(
    orchestrator, uow, session_id, store, monkeypatch
) -> None:
    from engine.core.errors import EngineError
    from engine.core.models import Memory
    from engine.memory.extractor import ExtractionResult

    async def two_memories(_uow, state, events, *, owners):
        event = events[0]
        return ExtractionResult(
            memories=[
                Memory(
                    world_id=state.world.id,
                    owner_character_id=owners[0].id,
                    summary="第一条 canonical 投影",
                    related_event_id=event.id,
                ),
                Memory(
                    world_id=state.world.id,
                    owner_character_id=owners[1].id,
                    summary="第二条 canonical 投影",
                    related_event_id=event.id,
                ),
            ],
            degraded=False,
            skipped=[],
        )

    original_add = uow.memories.add
    add_calls = 0

    async def fail_second_add(memory):
        nonlocal add_calls
        add_calls += 1
        if add_calls == 2:
            raise RuntimeError("injected partial projection crash")
        await original_add(memory)

    monkeypatch.setattr(orchestrator.d.memory, "extract", two_memories)
    monkeypatch.setattr(uow.memories, "add", fail_second_add)
    request = TurnRequest(
        session_id=session_id,
        text="我打坐修炼一个时辰",
        idempotency_key="partial-memory-retry-key",
    )
    memories_before = len(store.memories)

    with pytest.raises(EngineError, match="memory projection failed after canonical commit"):
        await orchestrator.play_turn(uow, request)

    assert len(store.memories) == memories_before

    result = await orchestrator.play_turn(uow, request)

    assert result.status is TurnStatus.COMPLETED
    assert len(store.memories) == memories_before + 2


async def test_narrative_retry_does_not_reactivate_due_director_event(
    orchestrator, uow, state, session_id, store, monkeypatch
) -> None:
    from engine.characters.schemas import DirectorDecision
    from engine.core.mutations import ChangeSet
    from engine.core.types import DirectorDecisionType, DirectorEventStatus
    from engine.director.lifecycle import DirectorEventLifecycleService

    participant = state.present_characters[0]
    scheduled = DirectorEventLifecycleService(orchestrator.d.pack).propose(
        state,
        DirectorDecision(
            decision=DirectorDecisionType.TRIGGER_EVENT,
            event_type="NPC_APPROACH",
            participants=[participant.key],
            proposal="有人按已有线索前来",
            schedule_after_minutes=1,
        ),
        [participant],
        None,
        session_id=session_id,
        turn_id="director-setup",
        turn_number=0,
    )
    async with uow:
        await uow.apply(ChangeSet(director_events=[scheduled]))
        await uow.commit()

    original_render = orchestrator.d.narrative.render
    calls = 0

    async def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected narrative crash after Director activation")
        return await original_render(*args, **kwargs)

    monkeypatch.setattr(orchestrator.d.narrative, "render", fail_once)
    request = TurnRequest(
        session_id=session_id,
        text="我打坐修炼一个时辰",
        idempotency_key="director-narrative-retry",
    )
    first = await orchestrator.play_turn(uow, request)
    stored_after_first = await uow.director_events.get(scheduled.id)
    canonical = [
        event for event in store.events if event.payload.get("director_event_id") == scheduled.id
    ]
    assert first.status is TurnStatus.NARRATIVE_FAILED
    assert stored_after_first is not None
    assert stored_after_first.status is DirectorEventStatus.RESOLVED
    assert len(canonical) == 1

    second = await orchestrator.play_turn(uow, request)
    canonical_after_retry = [
        event for event in store.events if event.payload.get("director_event_id") == scheduled.id
    ]
    assert second.status is TurnStatus.COMPLETED
    assert second.turn_id == first.turn_id
    assert len(canonical_after_retry) == 1


async def test_reusing_idempotency_key_for_different_input_is_rejected(
    orchestrator, uow, session_id
) -> None:
    from engine.core.errors import EngineError

    await orchestrator.play_turn(
        uow,
        TurnRequest(session_id=session_id, text="我环顾四周", idempotency_key="same-key"),
    )
    with pytest.raises(EngineError, match="different input"):
        await orchestrator.play_turn(
            uow,
            TurnRequest(session_id=session_id, text="我打坐修炼", idempotency_key="same-key"),
        )


async def test_events_are_appended_for_every_meaningful_turn(
    orchestrator, uow, session_id, store
) -> None:
    before = len(store.events)
    await orchestrator.play_turn(uow, TurnRequest(session_id=session_id, text="我打坐修炼一个时辰"))
    assert len(store.events) > before
    assert any(e.event_type == "CULTIVATION_SESSION" for e in store.events)


async def test_npc_killed_by_current_changeset_cannot_respond(orchestrator, uow, ctx) -> None:
    from engine.actions.schema import Action, ActionOutcome
    from engine.core import mutations as mut
    from engine.core.mutations import ChangeSet
    from engine.orchestrator.turn import TurnTrace

    target = ctx.state.present_characters[0]
    action = Action(
        action_type=ActionType.ATTACK,
        actor_id=ctx.state.player.id,
        target_id=target.id,
        raw_text="攻击目标",
    )
    outcome = ActionOutcome(
        action_type=ActionType.ATTACK,
        success=True,
        summary_key="ATTACK_HIT",
    )
    changes = ChangeSet(changes=[mut.character_death(target.id, reason="test")])
    trace = TurnTrace(turn_id="death-response-test")

    await orchestrator._run_npcs(uow, ctx, action, outcome, changes, trace)

    assert all(decision["npc"] != target.key for decision in trace.npc_decisions)


async def test_turn_and_trace_are_persisted(orchestrator, uow, session_id) -> None:
    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="我环顾四周")
    )
    stored = await uow.turns.get(result.turn_id)
    trace = await uow.turns.get_trace(result.turn_id)
    assert stored is not None
    assert stored["player_input"] == "我环顾四周"
    assert stored["idempotency_key"] == result.idempotency_key
    assert stored["status"] == str(TurnStatus.COMPLETED)
    assert stored["canonical_payload"]["outcome"]
    assert trace is not None
    assert trace["stage_timings"]


async def test_director_cooldown_reads_canonical_lifecycle_not_turn_debug(
    orchestrator, uow, state, session_id
) -> None:
    from engine.characters.schemas import DirectorDecision
    from engine.core.mutations import ChangeSet
    from engine.core.types import DirectorDecisionType
    from engine.director.lifecycle import DirectorEventLifecycleService

    session = await uow.sessions.get(session_id)
    assert session is not None
    participant = state.present_characters[0]
    record = DirectorEventLifecycleService(orchestrator.d.pack).propose(
        state,
        DirectorDecision(
            decision=DirectorDecisionType.TRIGGER_EVENT,
            event_type="NPC_APPROACH",
            participants=[participant.key],
            proposal="已有因果继续发展",
            schedule_after_minutes=60,
        ),
        [participant],
        None,
        session_id=session_id,
        turn_id="canonical-director-turn",
        turn_number=2,
    )
    async with uow:
        await uow.apply(ChangeSet(director_events=[record]))
        session.turn_number = 5
        await uow.sessions.save(session)
        await uow.commit()

    assert await orchestrator._turns_since_director(uow, session) == 3


async def test_cultivating_to_the_cap_then_breaking_through(
    orchestrator, uow, session_id, store
) -> None:
    """The full progression loop, driven only through natural language."""
    player_id = next(c.id for c in store.characters.values() if c.key == "player")
    for _ in range(12):
        await orchestrator.play_turn(uow, TurnRequest(session_id=session_id, text="我闭关修炼30日"))
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
    private_goal_steps = {
        step.description
        for character in store.characters.values()
        if character.goal_lifecycle is not None
        for step in character.goal_lifecycle.steps
    }

    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="我闭关修炼3年", debug=True)
    )
    assert result.debug["simulation"] is not None
    elapsed = result.state_changes["world_minute"][1] - result.state_changes["world_minute"][0]
    assert result.debug["simulation"]["strategy"] == "temporal_jump"
    assert result.debug["simulation"]["requested_minutes"] == elapsed
    assert result.debug["simulation"]["minutes"] == elapsed
    assert elapsed == 3 * 518_400

    factions_after = {f.id: dict(f.resources) for f in store.factions.values()}
    positions_after = {c.id: c.location_id for c in store.characters.values()}
    assert factions_after != factions_before, "factions must drift over three years"
    assert positions_after != positions_before, "NPCs must not stand still for three years"
    goal_events = [event for event in store.events if event.event_type == "NPC_GOAL_ACTION_RESULT"]
    assert goal_events, "important NPCs must pursue plans while the player is secluded"
    assert all(event.visibility.value == "PRIVATE" for event in goal_events)
    assert all(step not in result.narrative for step in private_goal_steps)


async def test_thirty_year_seclusion_ages_the_cast_and_resolves_natural_deaths(
    orchestrator, uow, session_id, store, pack
) -> None:
    before_ages = {character.id: character.age for character in store.characters.values()}
    start_minute = next(iter(store.worlds.values())).current_minute
    doomed = {
        character.id: character.key
        for character in store.characters.values()
        if character.alive
        and character.age + 30 >= pack.realms.realm(character.realm).lifespan_years
    }
    assert doomed, "the seeded cast should include mortal characters near end of life"
    doomed_goal_deadlines = {
        character.id: start_minute
        + (pack.realms.realm(character.realm).lifespan_years - character.age) * 518_400
        for character in store.characters.values()
        if character.id in doomed
        and character.goal_lifecycle is not None
        and character.age < pack.realms.realm(character.realm).lifespan_years
    }

    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="我闭关修炼三十年", debug=True)
    )
    elapsed = result.state_changes["world_minute"][1] - result.state_changes["world_minute"][0]
    assert elapsed == 30 * 518_400
    assert result.state_changes["character"]["age"] == [18, 48]
    assert result.debug["simulation"]["minutes"] == elapsed
    assert set(result.debug["simulation"]["natural_deaths"]) == set(doomed.values())
    assert len(result.debug["simulation"]["offline_events"]) <= 12

    for character_id in doomed:
        assert store.characters[character_id].age == before_ages[character_id] + 30
        assert not store.characters[character_id].alive
        assert store.characters[character_id].death_event_id
    death_ids = {event.id for event in store.events if event.event_type == "DEATH"}
    assert all(
        store.characters[character_id].death_event_id in death_ids for character_id in doomed
    )
    for character_id, death_minute in doomed_goal_deadlines.items():
        pre_death_actions = [
            event
            for event in store.events
            if event.event_type == "NPC_GOAL_ACTION_RESULT" and event.actor_id == character_id
        ]
        assert pre_death_actions
        assert all(event.world_minute < death_minute for event in pre_death_actions)


async def test_player_lie_remains_a_claim_and_cannot_rewrite_truth_or_grant_knowledge(
    orchestrator, uow, state, session_id, monkeypatch
) -> None:
    from engine.actions.intent_parser import ParsedIntent
    from engine.actions.schema import Action, ActionPlan, ActionPrimitive, PlayerIntent
    from engine.core.types import KnowledgeState

    fact = await uow.knowledge.get_fact_by_key(state.world.id, "fact_lin_is_sect_master_daughter")
    assert fact is not None and fact.truth_value is False
    target = None
    for character in state.present_characters:
        knowledge_state = await orchestrator.d.knowledge.state_of(
            uow, character.id, fact.key, state.world.id
        )
        if knowledge_state is KnowledgeState.UNKNOWN:
            target = character
            break
    assert target is not None
    claim = Action(
        action_type=ActionType.TALK,
        actor_id=state.player.id,
        target_id=target.id,
        utterance=fact.statement,
        raw_text=f"我告诉{target.name}：{fact.statement}",
    )
    parsed = ParsedIntent(
        intent=PlayerIntent(
            action_type=ActionType.TALK,
            target_key=target.key,
            utterance=claim.utterance,
            raw_text=claim.raw_text,
        ),
        action=claim,
        plan=ActionPlan(primitives=[ActionPrimitive(primitive_id="primary", action=claim)]),
        degraded=False,
    )

    async def parse_claim(*args, **kwargs):
        return parsed

    monkeypatch.setattr(orchestrator.d.intent_parser, "parse", parse_claim)
    result = await orchestrator.play_turn(
        uow,
        TurnRequest(
            session_id=session_id,
            text=claim.raw_text,
            idempotency_key="false-claim-does-not-become-truth",
            debug=True,
        ),
    )

    stored_fact = await uow.knowledge.get_fact_by_key(state.world.id, fact.key)
    assert stored_fact is not None and stored_fact.truth_value is False
    assert (
        await orchestrator.d.knowledge.state_of(uow, target.id, fact.key, state.world.id)
        is KnowledgeState.UNKNOWN
    )
    assert any(
        "asked_about_unknown_fact" in reason
        for decision in result.debug["npc_decisions"]
        if decision["npc"] == target.key
        for reason in decision["reasons"]
    )


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


async def test_dead_npcs_stay_dead_across_turns(
    orchestrator, uow, session_id, store, state
) -> None:
    if not state.present_characters:
        pytest.skip("nobody is in the starting scene")
    victim = state.present_characters[0]
    store.characters[victim.id].alive = False
    store.characters[victim.id].health = 0

    await orchestrator.play_turn(uow, TurnRequest(session_id=session_id, text="我闭关修炼3年"))
    assert not store.characters[victim.id].alive

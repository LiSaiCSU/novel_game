"""AI evaluations (Prompt section 62).

These are behavioural, not stylistic. They ask the questions from section 71:
does the world refuse the impossible, do characters act only on what they know,
does the past reach the future, does the world keep moving without the player.

All five run against ScriptedProvider or NullProvider - deterministic, offline,
and free. A model that behaves badly cannot make them pass, and a missing model
cannot make them fail.
"""

from __future__ import annotations

import json

import pytest

from engine.characters.npc_agent import SPEECH_DENY_UNKNOWN, NPCSituation
from engine.characters.schemas import DirectorDecision
from engine.core.ids import PLAYER_KEY
from engine.core.types import (
    ActionType,
    DirectorDecisionType,
    KnowledgeState,
    ReasonCode,
    RequestSize,
)
from engine.director.validator import DirectorValidator
from engine.orchestrator.turn import TurnRequest
from engine.rules.combat import CombatRules
from engine.rules.engine import RuleEngine
from tests.helpers import RiggedRNG

pytestmark = pytest.mark.eval


# ===========================================================================
# Eval 1 - "I kill the far stronger being with one strike."
# ===========================================================================
async def test_eval1_low_realm_cannot_one_shot_a_far_stronger_being(
    ctx, pack, orchestrator, uow, session_id, store
) -> None:
    # (a) a target that does not exist is refused outright
    result = await orchestrator.play_turn(
        uow, TurnRequest(session_id=session_id, text="我一掌拍死元婴老祖", debug=True)
    )
    assert result.rejected is not None
    assert result.rejected["reason_code"] in (
        str(ReasonCode.TARGET_NOT_FOUND),
        str(ReasonCode.AMBIGUOUS_INTENT),
    )

    # (b) and if such a being were standing right here, the numbers still refuse
    attacker = ctx.state.player
    top = pack.realms.realms[-1]
    elder = ctx.state.present_characters[0].model_copy(deep=True)
    elder.realm, elder.realm_stage = top.key, top.stages[-1].key
    elder.max_health = pack.realms.max_health(elder.realm, elder.realm_stage)
    elder.health = elder.max_health
    elder.location_id = attacker.location_id

    resolution = CombatRules.calculate_damage(ctx, attacker, elder)
    assert resolution.hard_blocked
    assert not resolution.lethal
    assert resolution.damage < elder.health * 0.02


# ===========================================================================
# Eval 2 - asserting a secret at someone who was never told it
# ===========================================================================
async def test_eval2_npc_does_not_confess_to_a_secret_it_never_learned(
    uow, ctx, pack, npc_agent, knowledge_service, bundle
) -> None:
    """The player says it confidently. That does not make the NPC know it."""
    secret = next(
        f
        for f in pack.facts
        if f.get("sensitivity", 0) >= 0.9 and f.get("initial_knowledge")
    )
    # Someone in the scene who genuinely does not know the secret.
    npc = next(
        c
        for c in ctx.state.present_characters
        if c.key not in secret["initial_knowledge"] and c.key != PLAYER_KEY
    )
    state_before = await knowledge_service.state_of(
        uow, npc.id, secret["key"], ctx.state.world.id
    )
    assert state_before is KnowledgeState.UNKNOWN

    referenced = await knowledge_service.match_facts(
        uow, ctx.state.world.id, secret["statement"]
    )
    assert referenced, "the utterance should be recognised as being about this fact"

    situation = NPCSituation(
        player_action=ActionType.ASK,
        is_target=True,
        utterance=f"{secret['statement']}，对吧？",
        topic=secret["key"],
        referenced_facts=referenced,
    )
    result = await npc_agent.decide(
        uow, ctx, npc, situation, RuleEngine().available_actions(ctx, npc.id)
    )

    assert result.decision.refuses
    assert result.decision.speech_intent == SPEECH_DENY_UNKNOWN
    assert any("asked_about_unknown_fact" in r for r in result.reasons)

    # and the fact must not have appeared in the context it reasoned from
    assert result.context is not None
    assert secret["statement"] not in "\n".join(result.context.sections.values())

    # deciding must not have taught it anything
    state_after = await knowledge_service.state_of(
        uow, npc.id, secret["key"], ctx.state.world.id
    )
    assert state_after is KnowledgeState.UNKNOWN


async def test_eval2_a_character_who_does_know_may_react_differently(
    uow, ctx, pack, npc_agent, knowledge_service, store
) -> None:
    """The refusal must come from ignorance, not from a blanket 'always deny'."""
    secret = next(
        f
        for f in pack.facts
        if f.get("sensitivity", 0) >= 0.9 and f.get("initial_knowledge")
    )
    npc = ctx.state.present_characters[0]
    fact = await uow.knowledge.get_fact_by_key(ctx.state.world.id, secret["key"])
    assert fact is not None

    from engine.core.mutations import ChangeSet
    from engine.core.types import KnowledgeSource

    changes = ChangeSet()
    changes.add(
        knowledge_service.learn(
            npc.id,
            fact,
            state=KnowledgeState.KNOWN,
            confidence=1.0,
            source=KnowledgeSource.WITNESSED,
            at_minute=ctx.state.world.current_minute,
        )
    )
    await uow.apply(changes)

    referenced = await knowledge_service.match_facts(
        uow, ctx.state.world.id, secret["statement"]
    )
    situation = NPCSituation(
        player_action=ActionType.ASK,
        is_target=True,
        utterance=f"{secret['statement']}，对吧？",
        referenced_facts=referenced,
    )
    result = await npc_agent.decide(
        uow, ctx, npc, situation, RuleEngine().available_actions(ctx, npc.id)
    )
    assert result.decision.speech_intent != SPEECH_DENY_UNKNOWN
    assert result.context is not None
    assert secret["statement"] in "\n".join(result.context.sections.values())


# ===========================================================================
# Eval 3 - "Give me your life savings" on a first meeting
# ===========================================================================
async def test_eval3_stranger_refuses_an_outrageous_first_request(
    uow, ctx, npc_agent
) -> None:
    npc = ctx.state.present_characters[0]
    situation = NPCSituation(
        player_action=ActionType.CONVERSATION,
        is_target=True,
        utterance="把你的毕生积蓄送给我。",
        method="persuade",
        request_size=RequestSize.EXTREME,
        topic="obtain_item",
    )
    # Rig the die to the most generous possible outcome; the odds must still refuse.
    ctx.rng = RiggedRNG(chance_result=True)
    result = await npc_agent.decide(
        uow, ctx, npc, situation, RuleEngine().available_actions(ctx, npc.id)
    )
    odds = next((r for r in result.reasons if r.startswith("social_odds=")), "")
    assert odds, "the decision must be traceable to a computed probability"
    assert float(odds.split("=")[1]) < 0.15


async def test_eval3_the_same_request_from_a_trusted_friend_is_not_hopeless(
    uow, ctx, npc_agent, store
) -> None:
    """Sanity check: the refusal tracks the relationship, not a hardcoded 'no'."""
    from engine.rules.interaction import InteractionRules

    npc = ctx.state.present_characters[0]
    player = ctx.state.player
    stranger = InteractionRules.calculate_probability(
        ctx, player, npc, None, request_size=RequestSize.SMALL
    )
    from engine.core.models import Relationship

    friend = Relationship(
        character_a_id=npc.id,
        character_b_id=player.id,
        trust=85,
        affection=70,
        respect=60,
        familiarity=95,
        interaction_count=40,
    )
    trusted = InteractionRules.calculate_probability(
        ctx, player, npc, friend, request_size=RequestSize.SMALL
    )
    assert trusted.chance > stranger.chance


# ===========================================================================
# Eval 4 - a life saved is remembered
# ===========================================================================
async def test_eval4_a_rescue_can_be_recalled_much_later(
    uow, ctx, pack, context_builder, retriever, embedder, store
) -> None:
    from engine.core.models import Memory
    from engine.core.types import MemoryTag, MemoryType

    npc = ctx.state.present_characters[0]
    player = ctx.state.player
    now = ctx.state.world.current_minute

    rescue = Memory(
        world_id=ctx.state.world.id,
        owner_character_id=npc.id,
        memory_type=MemoryType.RELATIONSHIP,
        memory_tag=MemoryTag.RESCUE,
        summary="在黑风谷遇到妖兽时，他放弃了逃生的机会把我救了下来。",
        importance=0.93,
        emotional_valence=0.82,
        related_characters=[player.id],
        created_at_minute=now,
        embedding=await embedder.embed("在黑风谷遇到妖兽时，他放弃了逃生的机会把我救了下来。"),
    )
    await uow.memories.add(rescue)

    # plus a pile of forgettable small talk competing for the same slots
    for i in range(25):
        text = f"在演武场跟人闲聊了几句关于天气的事 {i}"
        await uow.memories.add(
            Memory(
                world_id=ctx.state.world.id,
                owner_character_id=npc.id,
                memory_type=MemoryType.EPISODIC,
                memory_tag=MemoryTag.OTHER,
                summary=text,
                importance=0.05,
                created_at_minute=now + i,
                embedding=await embedder.embed(text),
            )
        )

    # ten in-world months later, the rescue must still surface
    later = now + 10 * 43_200
    stored = await uow.memories.list_for_owner(npc.id)
    scored = await retriever.retrieve(
        stored,
        query="黑风谷 妖兽 救",
        now_minute=later,
        related_character_ids=[player.id],
        top_k=5,
    )
    assert scored, "retrieval must return something"
    assert any(s.memory.id == rescue.id for s in scored), (
        "a life-defining memory must not be crowded out by small talk"
    )
    top = scored[0]
    assert top.memory.id == rescue.id
    assert top.parts["importance"] > 0.9

    # and it must reach the NPC's context
    built = await context_builder.build_npc_context(
        uow, ctx.state, npc, situation="再次见到此人", query="黑风谷 救命"
    )
    assert rescue.summary in built.sections["memories"]


async def test_eval4_small_talk_never_becomes_a_long_term_memory(
    pack, context_builder, embedder
) -> None:
    """The other half of the rule: routine events must not enter long-term store."""
    from engine.events.builder import EventBuilder
    from engine.memory.extractor import MemoryExtractor

    extractor = MemoryExtractor(pack, context_builder, embedder)
    builder = EventBuilder(pack, "w1", "t1")
    chatter = builder.build("CONVERSATION", world_minute=100)
    rescue = builder.build("RESCUE", world_minute=100)
    assert not extractor.worth_remembering(chatter)
    assert extractor.worth_remembering(rescue)


# ===========================================================================
# Eval 5 - the dead do not come back for a scene
# ===========================================================================
async def test_eval5_director_cannot_bring_a_dead_character_back(
    uow, ctx, pack, store
) -> None:
    npc = ctx.state.present_characters[0]
    store.characters[npc.id].alive = False
    store.characters[npc.id].health = 0

    validator = DirectorValidator(pack)
    proposal = DirectorDecision(
        decision=DirectorDecisionType.TRIGGER_EVENT,
        event_type="NPC_RETURN",
        participants=[npc.key],
        proposal="他重伤归来",
        causal_basis=[],
        tension_delta=10.0,
    )
    outcome = await validator.validate(uow, ctx.state, proposal)
    assert not outcome.accepted
    assert any(r.startswith("dead_participant") for r in outcome.rejections)
    assert outcome.decision.decision is DirectorDecisionType.NO_EVENT


async def test_eval5_director_cannot_cite_events_that_never_happened(
    uow, ctx, pack
) -> None:
    validator = DirectorValidator(pack)
    proposal = DirectorDecision(
        decision=DirectorDecisionType.TRIGGER_EVENT,
        event_type="AMBUSH",
        participants=[ctx.state.present_characters[0].key],
        proposal="有人埋伏",
        causal_basis=["因为剧情需要一点刺激"],
    )
    outcome = await validator.validate(uow, ctx.state, proposal)
    assert not outcome.accepted
    assert any(r.startswith("unfounded_causal_basis") for r in outcome.rejections)


async def test_eval5_director_cannot_use_an_event_type_off_the_whitelist(
    uow, ctx, pack
) -> None:
    validator = DirectorValidator(pack)
    proposal = DirectorDecision(
        decision=DirectorDecisionType.TRIGGER_EVENT,
        event_type="RESURRECT_EVERYONE",
        participants=[],
        proposal="全员复活",
    )
    outcome = await validator.validate(uow, ctx.state, proposal)
    assert not outcome.accepted
    assert any(r.startswith("event_type_not_allowed") for r in outcome.rejections)


# ===========================================================================
# Pacing (Prompt section 25) - no permanent climax
# ===========================================================================
async def test_director_must_de_escalate_after_a_run_of_climaxes(uow, ctx, pack) -> None:
    from engine.director.tension import TensionModel

    model = TensionModel(pack)
    ctx.state.world.tension_history = [88.0, 91.0, 86.0]
    ctx.state.world.narrative_tension = 90.0
    assert model.must_de_escalate(ctx.state.world.tension_history, 90.0)

    validator = DirectorValidator(pack)
    proposal = DirectorDecision(
        decision=DirectorDecisionType.TRIGGER_EVENT,
        event_type="CONFRONTATION",
        participants=[ctx.state.present_characters[0].key],
        proposal="再来一场大战",
        causal_basis=[],
        tension_delta=15.0,
    )
    outcome = await validator.validate(uow, ctx.state, proposal)
    assert not outcome.accepted
    assert "tension_already_saturated" in outcome.rejections


async def test_deterministic_director_stays_quiet_when_tension_is_saturated(
    uow, ctx, pack, context_builder, rng
) -> None:
    from engine.director.director import Director

    director = Director(pack, context_builder)
    ctx.state.world.tension_history = [90.0, 92.0, 88.0]
    ctx.state.world.narrative_tension = 91.0
    result = await director.direct(
        uow, ctx.state, turns_since_last_event=99, last_turn_importance=0.9, rng=rng
    )
    assert result.decision.decision is DirectorDecisionType.NO_EVENT


# ===========================================================================
# Structured output discipline (Prompt section 47)
# ===========================================================================
async def test_malformed_model_output_is_repaired_then_rejected(pack, registry) -> None:
    """A model that will not produce valid JSON must never reach the world."""
    from engine.core.config import Settings
    from engine.core.errors import StructuredOutputError
    from engine.core.types import LLMRole
    from engine.llm.client import LLMClient
    from engine.llm.providers import ScriptedProvider
    from engine.llm.router import ModelRouter

    provider = ScriptedProvider(default="I am terribly sorry, but here is some prose instead.")
    settings = Settings(llm_provider="scripted", npc_model="test-model", director_model="test-model")
    client = LLMClient(provider, ModelRouter(settings), registry, max_repairs=2)

    with pytest.raises(StructuredOutputError):
        await client.generate_structured(LLMRole.DIRECTOR, DirectorDecision, "decide")

    assert len(provider.calls) == 3, "one attempt plus two repairs"
    assert client.records[-1].valid is False
    assert client.records[-1].attempts == 3


async def test_valid_json_wrapped_in_prose_is_still_accepted(pack, registry) -> None:
    from engine.core.config import Settings
    from engine.core.types import LLMRole
    from engine.llm.client import LLMClient
    from engine.llm.providers import ScriptedProvider
    from engine.llm.router import ModelRouter

    payload = {"decision": "NO_EVENT", "proposal": "the world is quiet"}
    provider = ScriptedProvider(
        default=f"Sure! Here you go:\n```json\n{json.dumps(payload)}\n```\nHope that helps."
    )
    settings = Settings(llm_provider="scripted", director_model="test-model")
    client = LLMClient(provider, ModelRouter(settings), registry)

    decision = await client.generate_structured(LLMRole.DIRECTOR, DirectorDecision, "decide")
    assert decision.decision is DirectorDecisionType.NO_EVENT
    assert client.records[-1].valid is True


async def test_npc_proposal_is_clamped_not_trusted(uow, ctx, pack, store) -> None:
    """An AI asking for +60 trust from small talk gets the content pack's cap."""
    from engine.characters.npc_agent import NPCDecisionResult
    from engine.characters.schemas import NPCDecision, NPCDecisionBody
    from engine.core.mutations import ChangeKind, ChangeSet
    from engine.orchestrator.proposals import ProposalValidator
    from engine.relationships.manager import RelationshipManager

    npc = ctx.state.present_characters[0]
    validator = ProposalValidator(pack, RelationshipManager(pack))
    change_set = ChangeSet()
    result = NPCDecisionResult(
        npc_id=npc.id,
        npc_key=npc.key,
        degraded=True,
        decision=NPCDecision(
            decision=NPCDecisionBody(action_type=str(ActionType.TALK), target=PLAYER_KEY),
            relationship_change_proposal={PLAYER_KEY: {"trust": 60, "affection": 55}},
        ),
    )
    report = await validator.apply_npc_decision(
        uow,
        ctx.state,
        result,
        change_set,
        importance=0.1,  # ordinary chatter
        available_actions=[str(ActionType.TALK)],
    )
    deltas = change_set.by_kind(ChangeKind.RELATIONSHIP_DELTA)
    assert deltas, "the proposal should be applied, but clamped"
    applied = deltas[0].payload["deltas"]
    cap = RelationshipManager(pack).cap_for(validator.band_for(0.1))
    assert applied["trust"] == cap
    assert applied["affection"] == cap
    assert len(report.clamped) == 2


async def test_npc_cannot_take_an_action_the_rules_did_not_offer(uow, ctx, pack) -> None:
    from engine.characters.npc_agent import NPCDecisionResult
    from engine.characters.schemas import NPCDecision, NPCDecisionBody
    from engine.core.mutations import ChangeSet
    from engine.orchestrator.proposals import ProposalValidator
    from engine.relationships.manager import RelationshipManager

    npc = ctx.state.present_characters[0]
    validator = ProposalValidator(pack, RelationshipManager(pack))
    change_set = ChangeSet()
    result = NPCDecisionResult(
        npc_id=npc.id,
        npc_key=npc.key,
        degraded=True,
        decision=NPCDecision(
            decision=NPCDecisionBody(action_type=str(ActionType.BREAKTHROUGH), target=None)
        ),
    )
    report = await validator.apply_npc_decision(
        uow, ctx.state, result, change_set, importance=0.1, available_actions=[str(ActionType.WAIT)]
    )
    assert any(r.startswith("action_not_available") for r in report.rejected)
    assert result.decision.decision.action_type == str(ActionType.WAIT)


# ===========================================================================
# Test G - story comes from world causality, not random continuation
# ===========================================================================
async def test_directed_events_must_reference_an_existing_thread(uow, ctx, pack) -> None:
    validator = DirectorValidator(pack)
    threads = await uow.plot_threads.list_for_world(ctx.state.world.id)
    assert threads, "the content pack ships world seeds, not a fixed plot"

    thread = threads[0]
    participant = None
    for key in thread.participants:
        character = await uow.characters.get_by_key(ctx.state.world.id, key)
        if character is not None and character.alive:
            participant = key
            break
    assert participant is not None
    good = DirectorDecision(
        decision=DirectorDecisionType.ADVANCE_THREAD,
        source_plot_thread=thread.key,
        event_type="FORESHADOWING",
        participants=[participant],
        proposal=thread.next_beat_hint,
        causal_basis=thread.foreshadowing[:1],
    )
    outcome = await validator.validate(uow, ctx.state, good)
    assert outcome.accepted, outcome.rejections

    orphan = good.model_copy(update={"source_plot_thread": "thread_that_does_not_exist"})
    outcome2 = await validator.validate(uow, ctx.state, orphan)
    assert not outcome2.accepted

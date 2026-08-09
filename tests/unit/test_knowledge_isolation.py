"""THE core test (Prompt section 30).

An NPC's context must contain what that NPC knows and nothing else. If this
file ever goes red, the product's central premise is broken - characters would
be reasoning from a god's-eye view of the database.
"""

from __future__ import annotations

import pytest

from engine.core.ids import PLAYER_KEY
from engine.core.types import KnowledgeSource, KnowledgeState
from engine.knowledge.service import KnowledgeService
from engine.world.state_view import WorldStateView


async def _all_context_text(context_builder, uow, state, npc) -> str:
    built = await context_builder.build_npc_context(uow, state, npc, situation="test")
    return "\n".join(built.sections.values())


@pytest.fixture
def secret_fact(pack):
    """A fact with exactly one or two seeded knowers - the sharper the better."""
    candidates = [
        f
        for f in pack.facts
        if f.get("sensitivity", 0) >= 0.9 and len(f.get("initial_knowledge") or {}) >= 2
    ]
    assert candidates, "content pack must define at least one high-sensitivity secret"
    return candidates[0]


# ---------------------------------------------------------------------------
async def test_content_pack_secret_is_not_universal(secret_fact, pack) -> None:
    """Precondition: the fixture is actually a secret, not common knowledge."""
    knowers = set(secret_fact["initial_knowledge"])
    everyone = {c["key"] for c in pack.characters}
    assert knowers < everyone
    assert PLAYER_KEY not in knowers


async def test_secret_never_appears_in_an_ignorant_npcs_context(
    uow, state: WorldStateView, context_builder, secret_fact, bundle
) -> None:
    """NPC A knows SECRET_X; NPC B does not. B's context must never contain it."""
    statement = secret_fact["statement"]
    knowers = set(secret_fact["initial_knowledge"])

    ignorant = [
        c
        for c in bundle.characters
        if c.key not in knowers and c.key != PLAYER_KEY
    ]
    assert ignorant, "need at least one character who does not know the secret"

    for npc in ignorant:
        text = await _all_context_text(context_builder, uow, state, npc)
        assert statement not in text, (
            f"{npc.key} must not see the secret {secret_fact['key']!r} in its context"
        )


async def test_a_knower_does_see_the_secret(
    uow, state: WorldStateView, context_builder, secret_fact, bundle
) -> None:
    """The firewall must not be a blanket blackout - knowers still know."""
    knower_key = next(
        key
        for key, spec in secret_fact["initial_knowledge"].items()
        if spec["state"] in ("KNOWN", "BELIEVED")
    )
    npc = bundle.character_by_key(knower_key)
    assert npc is not None
    text = await _all_context_text(context_builder, uow, state, npc)
    assert secret_fact["statement"] in text


async def test_truth_value_is_never_exposed(
    uow, state: WorldStateView, context_builder, bundle, pack
) -> None:
    """Belief strength may be shown. Objective truth may not."""
    for npc in bundle.characters[:12]:
        built = await context_builder.build_npc_context(uow, state, npc, situation="test")
        text = "\n".join(built.sections.values())
        assert "truth_value" not in text
        assert "truth=" not in text.lower()


async def test_a_false_belief_is_presented_as_belief_not_fact(
    uow, state: WorldStateView, context_builder, bundle, pack
) -> None:
    """A character who believes something untrue still gets to believe it."""
    false_facts = [f for f in pack.facts if f.get("truth_value") is False]
    if not false_facts:
        pytest.skip("content pack has no deliberately false rumour")
    rumour = false_facts[0]
    believer_key = next(
        (
            key
            for key, spec in (rumour.get("initial_knowledge") or {}).items()
            if spec["state"] in ("BELIEVED", "HEARD")
        ),
        None,
    )
    assert believer_key, "the false rumour needs a believer to be a useful fixture"
    npc = bundle.character_by_key(believer_key)
    assert npc is not None
    text = await _all_context_text(context_builder, uow, state, npc)
    assert rumour["statement"] in text
    # and the character who knows better must not be shown it as truth
    disbeliever_key = next(
        (
            key
            for key, spec in (rumour.get("initial_knowledge") or {}).items()
            if spec["state"] == "DISBELIEVED"
        ),
        None,
    )
    if disbeliever_key:
        other = bundle.character_by_key(disbeliever_key)
        assert other is not None
        other_text = await _all_context_text(context_builder, uow, state, other)
        hedges = KnowledgeService(pack).hedges()
        assert hedges["DISBELIEVED"] in other_text


async def test_unknown_rows_are_filtered_at_the_repository(
    uow, bundle, secret_fact, pack
) -> None:
    """Defence in depth: list_known() itself refuses to return UNKNOWN rows."""
    ignorant = next(
        c
        for c in bundle.characters
        if c.key not in secret_fact["initial_knowledge"] and c.key != PLAYER_KEY
    )
    rows = await uow.knowledge.list_known(ignorant.id)
    assert all(k.knowledge_state is not KnowledgeState.UNKNOWN for k, _ in rows)
    assert all(f.key != secret_fact["key"] for _k, f in rows)


async def test_beliefs_of_excludes_unknown(
    uow, bundle, knowledge_service, secret_fact
) -> None:
    ignorant = next(
        c
        for c in bundle.characters
        if c.key not in secret_fact["initial_knowledge"] and c.key != PLAYER_KEY
    )
    beliefs = await knowledge_service.beliefs_of(uow, ignorant.id)
    assert secret_fact["key"] not in {b.fact_key for b in beliefs}


async def test_private_events_do_not_leak_into_other_npc_contexts(
    uow, state: WorldStateView, context_builder, bundle, pack
) -> None:
    """An event only its participants perceived must not show up elsewhere."""
    from engine.events.builder import EventBuilder

    builder = EventBuilder(pack, state.world.id, turn_id="t-secret")
    actor = bundle.characters[0]
    outsider = next(c for c in bundle.characters if c.id != actor.id)
    secret_event = builder.build(
        "THEFT",
        actor_id=actor.id,
        location_id=actor.location_id,
        payload={"summary": "MARKER_SECRET_THEFT_PAYLOAD"},
        world_minute=state.world.current_minute,
        witnesses=[actor.id],
    )
    await uow.events.append(secret_event)

    outsider_text = await _all_context_text(context_builder, uow, state, outsider)
    assert "MARKER_SECRET_THEFT_PAYLOAD" not in outsider_text

    actor_text = await _all_context_text(context_builder, uow, state, actor)
    assert "MARKER_SECRET_THEFT_PAYLOAD" in actor_text


async def test_context_stays_inside_its_token_budget(
    uow, state: WorldStateView, pack, knowledge_service, retriever, embedder, bundle
) -> None:
    from engine.context.builder import ContextBuilder

    tight = ContextBuilder(
        pack, knowledge_service, retriever, embedder, budgets={"npc": 200}
    )
    npc = bundle.characters[0]
    built = await tight.build_npc_context(uow, state, npc, situation="test")
    assert built.estimated_tokens <= 400  # identity is never dropped
    assert built.truncated


async def test_learning_a_fact_changes_only_that_character(
    uow, state: WorldStateView, context_builder, bundle, knowledge_service, secret_fact
) -> None:
    """Telling one person a secret does not tell the whole world."""
    from engine.core.mutations import ChangeSet

    fact = next(f for f in await uow.knowledge.list_facts(state.world.id) if f.key == secret_fact["key"])
    ignorant = [
        c for c in bundle.characters if c.key not in secret_fact["initial_knowledge"] and c.key != PLAYER_KEY
    ]
    learner, bystander = ignorant[0], ignorant[1]

    change_set = ChangeSet()
    change_set.add(
        knowledge_service.learn(
            learner.id,
            fact,
            state=KnowledgeState.BELIEVED,
            confidence=0.8,
            source=KnowledgeSource.TOLD_BY,
            at_minute=state.world.current_minute,
        )
    )
    await uow.apply(change_set)

    learner_text = await _all_context_text(context_builder, uow, state, learner)
    bystander_text = await _all_context_text(context_builder, uow, state, bystander)
    assert secret_fact["statement"] in learner_text
    assert secret_fact["statement"] not in bystander_text

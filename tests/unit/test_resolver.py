"""ActionResolver: rules -> facts, still with no LLM in sight."""

from __future__ import annotations

import pytest

from database.memory_uow import MemoryUnitOfWork
from engine.actions.resolver import ActionResolver
from engine.actions.schema import Action
from engine.contentpack.pack import ContentPack
from engine.core.mutations import ChangeKind
from engine.core.types import ActionType, ReasonCode
from engine.events.builder import EventBuilder
from engine.relationships.manager import RelationshipManager
from engine.rules.base import RuleContext
from engine.rules.economy import EconomyRules
from engine.rules.engine import RuleEngine
from tests.helpers import RiggedRNG


@pytest.fixture
def resolver(pack: ContentPack, ctx: RuleContext) -> ActionResolver:
    return ActionResolver(
        EventBuilder(pack, ctx.state.world.id, turn_id="t1"), RelationshipManager(pack)
    )


@pytest.fixture
def engine() -> RuleEngine:
    return RuleEngine()


def _run(engine: RuleEngine, resolver: ActionResolver, ctx: RuleContext, action: Action):
    result = engine.validate_action(ctx, action)
    return resolver.resolve(ctx, action, result)


def test_rejected_action_produces_no_state_change(ctx, engine, resolver) -> None:
    action = Action(
        action_type=ActionType.MOVE, actor_id=ctx.state.player.id, target_location_id="nope"
    )
    outcome, changes = _run(engine, resolver, ctx, action)
    assert not outcome.success
    assert outcome.time_cost_minutes == 0
    assert changes.changes == []
    assert changes.events[0].event_type == "REJECTED_ACTION"
    assert outcome.facts["reason_code"] == str(ReasonCode.LOCATION_NOT_FOUND)


def test_move_produces_a_location_change_and_costs_time(ctx, engine, resolver) -> None:
    here = ctx.state.location_key()
    destination = next(
        loc for loc in ctx.state.graph.all() if loc.key != here and loc.accessible and loc.travel_minutes
    )
    action = Action(
        action_type=ActionType.MOVE, actor_id=ctx.state.player.id, target_location_id=destination.id
    )
    outcome, changes = _run(engine, resolver, ctx, action)
    assert outcome.success
    assert outcome.time_cost_minutes > 0
    moves = changes.by_kind(ChangeKind.CHARACTER_LOCATION)
    assert len(moves) == 1
    assert moves[0].after == destination.id


def test_cultivation_advances_progress_within_the_cap(ctx, engine, resolver) -> None:
    action = Action(
        action_type=ActionType.CULTIVATE, actor_id=ctx.state.player.id, duration_minutes=480
    )
    outcome, changes = _run(engine, resolver, ctx, action)
    assert outcome.success
    field_changes = {c.field: c for c in changes.by_kind(ChangeKind.CHARACTER_FIELD)}
    assert "cultivation_progress" in field_changes
    change = field_changes["cultivation_progress"]
    assert 0.0 <= change.after <= 1.0
    assert change.after > change.before


def test_breakthrough_success_updates_realm_and_logs_before_after(
    ctx, engine, resolver, pack: ContentPack
) -> None:
    player = ctx.state.player
    player.cultivation_progress = 1.0
    ctx.rng = RiggedRNG(chance_result=True)

    action = Action(action_type=ActionType.BREAKTHROUGH, actor_id=player.id)
    outcome, changes = _run(engine, resolver, ctx, action)
    assert outcome.success
    fields = {c.field: c for c in changes.by_kind(ChangeKind.CHARACTER_FIELD)}
    assert fields["realm_stage"].after != player.realm_stage or fields["realm"].after != player.realm
    assert fields["cultivation_progress"].after == 0.0

    event = next(e for e in changes.events if e.event_type == "BREAKTHROUGH")
    assert event.before["display"] and event.after["display"]
    assert event.before["display"] != event.after["display"]
    assert event.causes
    assert event.rng_seed


def test_breakthrough_failure_hurts_and_deepens_the_bottleneck(ctx, engine, resolver) -> None:
    player = ctx.state.player
    player.cultivation_progress = 1.0
    ctx.rng = RiggedRNG(chance_result=False)

    action = Action(action_type=ActionType.BREAKTHROUGH, actor_id=player.id)
    outcome, changes = _run(engine, resolver, ctx, action)
    assert not outcome.success
    fields = {c.field: c for c in changes.by_kind(ChangeKind.CHARACTER_FIELD)}
    assert fields["health"].after < player.health
    assert fields["injuries"].after > player.injuries
    assert fields["bottleneck"].after > player.bottleneck
    assert any(e.event_type == "BREAKTHROUGH_FAILED" for e in changes.events)


def test_attack_that_kills_marks_death_once(ctx, engine, resolver) -> None:
    target = ctx.state.present_characters[0]
    target.health = 1
    target.max_health = 1
    ctx.rng = RiggedRNG(chance_result=True)

    action = Action(action_type=ActionType.ATTACK, actor_id=ctx.state.player.id, target_id=target.id)
    outcome, changes = _run(engine, resolver, ctx, action)
    deaths = changes.by_kind(ChangeKind.CHARACTER_DEATH)
    if outcome.facts.get("hit") and outcome.facts.get("damage", 0) >= 1:
        assert len(deaths) == 1
        assert deaths[0].target_id == target.id
        assert any(e.event_type == "DEATH" for e in changes.events)


def test_selling_moves_currency_the_right_way(ctx, engine, resolver, pack: ContentPack) -> None:
    currency = EconomyRules.currency_key(ctx)
    sellable = next(
        row.item_key
        for row in ctx.state.inventory
        if row.item_key != currency and int((pack.item(row.item_key) or {}).get("value", 0)) > 0
    )
    action = Action(
        action_type=ActionType.SELL, actor_id=ctx.state.player.id, item_key=sellable, quantity=1
    )
    outcome, changes = _run(engine, resolver, ctx, action)
    assert outcome.success
    removed = changes.by_kind(ChangeKind.INVENTORY_REMOVE)
    added = changes.by_kind(ChangeKind.INVENTORY_ADD)
    assert removed[0].payload["item_key"] == sellable
    assert added[0].payload["item_key"] == currency
    assert added[0].payload["quantity"] > 0


def test_query_actions_change_nothing(ctx, engine, resolver) -> None:
    for query in (
        ActionType.QUERY_STATUS,
        ActionType.QUERY_INVENTORY,
        ActionType.QUERY_RELATIONSHIPS,
        ActionType.QUERY_QUESTS,
    ):
        action = Action(action_type=query, actor_id=ctx.state.player.id)
        outcome, changes = _run(engine, resolver, ctx, action)
        assert outcome.success
        assert outcome.time_cost_minutes == 0
        assert changes.is_empty()


def test_conversation_only_nudges_familiarity(ctx, engine, resolver) -> None:
    target = ctx.state.present_characters[0]
    action = Action(
        action_type=ActionType.CONVERSATION, actor_id=ctx.state.player.id, target_id=target.id
    )
    outcome, changes = _run(engine, resolver, ctx, action)
    assert outcome.success
    deltas = changes.by_kind(ChangeKind.RELATIONSHIP_DELTA)
    assert len(deltas) == 1
    payload = deltas[0].payload["deltas"]
    assert set(payload) == {"familiarity"}
    assert payload["familiarity"] <= 2


async def test_resolution_is_reproducible_for_the_same_seed(
    pack: ContentPack, bundle, player_id: str
) -> None:
    """Same world seed + same event key => same dice."""
    from database.memory_uow import MemoryStore
    from engine.rng.game_rng import event_rng
    from engine.world.state_view import build_world_state

    async def run_once() -> dict:
        store = MemoryStore()
        store.load(bundle.model_copy(deep=True) if hasattr(bundle, "model_copy") else bundle)
        uow = MemoryUnitOfWork(store)
        state = await build_world_state(uow, pack, bundle.world.id, player_id)
        rng = event_rng(bundle.world.world_seed, "s1", "turn-1:cultivate")
        ctx = RuleContext(pack=pack, state=state, rng=rng)
        engine = RuleEngine()
        resolver = ActionResolver(
            EventBuilder(pack, state.world.id, "t1"), RelationshipManager(pack)
        )
        action = Action(
            action_type=ActionType.CULTIVATE, actor_id=player_id, duration_minutes=300
        )
        outcome, _ = resolver.resolve(ctx, action, engine.validate_action(ctx, action))
        return outcome.facts

    first = await run_once()
    second = await run_once()
    assert first["progress_after"] == second["progress_after"]

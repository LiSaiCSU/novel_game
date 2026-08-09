"""Event log and ConsistencyGuard (Prompt sections 17, 63)."""

from __future__ import annotations

import pytest

from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.errors import ConsistencyViolation
from engine.core.mutations import ChangeSet
from engine.core.types import Visibility
from engine.events.builder import EventBuilder, witnesses_for
from engine.world.consistency import ConsistencyGuard
from engine.world.state_view import WorldStateView


@pytest.fixture
def guard(pack: ContentPack) -> ConsistencyGuard:
    return ConsistencyGuard(pack)


@pytest.fixture
def builder(pack: ContentPack, state: WorldStateView) -> EventBuilder:
    return EventBuilder(pack, state.world.id, turn_id="turn-1")


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------
def test_event_records_before_after_and_causes(builder: EventBuilder) -> None:
    event = builder.build(
        "BREAKTHROUGH",
        actor_id="player",
        before={"realm": "a"},
        after={"realm": "b"},
        causes=["seclusion", "pill"],
        world_minute=1234,
        rng_seed="deadbeef",
    )
    assert event.before != event.after
    assert event.causes == ["seclusion", "pill"]
    assert event.world_minute == 1234
    assert event.rng_seed == "deadbeef"
    assert event.importance > 0.5  # a breakthrough matters


def test_event_importance_and_visibility_come_from_content(
    builder: EventBuilder, pack: ContentPack
) -> None:
    event = builder.build("CONVERSATION")
    assert event.importance == pack.event_importance("CONVERSATION")
    assert str(event.visibility) == pack.event_visibility("CONVERSATION")


def test_secret_events_have_only_the_actor_as_witness(state: WorldStateView) -> None:
    witnesses = witnesses_for(Visibility.SECRET, state.present_characters, "actor-1")
    assert witnesses == ["actor-1"]


def test_public_events_are_witnessed_by_everyone_present(state: WorldStateView) -> None:
    witnesses = witnesses_for(Visibility.PUBLIC, state.present_characters, "actor-1")
    assert len(witnesses) == len([c for c in state.present_characters if c.alive]) + 1


async def test_event_log_is_append_only(uow, builder: EventBuilder, state: WorldStateView) -> None:
    first = builder.build("OBSERVATION", actor_id=state.player.id, world_minute=10)
    await uow.events.append(first)
    stored = await uow.events.get(first.id)
    assert stored is not None

    # mutating the caller's copy must not change what was stored
    first.importance = 0.99
    stored_again = await uow.events.get(first.id)
    assert stored_again is not None
    assert stored_again.importance != 0.99

    assert not hasattr(uow.events, "update")
    assert not hasattr(uow.events, "delete")


async def test_causal_chain_can_be_followed(uow, builder: EventBuilder, state: WorldStateView) -> None:
    root = builder.build("CONFRONTATION", actor_id=state.player.id, world_minute=10)
    await uow.events.append(root)
    consequence = builder.build(
        "DEATH", actor_id=state.player.id, world_minute=20, cause_event_ids=[root.id]
    )
    await uow.events.append(consequence)

    stored = await uow.events.get(consequence.id)
    assert stored is not None
    parent = await uow.events.get(stored.cause_event_ids[0])
    assert parent is not None
    assert parent.event_type == "CONFRONTATION"


# ---------------------------------------------------------------------------
# ConsistencyGuard
# ---------------------------------------------------------------------------
def test_guard_passes_a_normal_change_set(guard, state: WorldStateView) -> None:
    cs = ChangeSet()
    cs.add(mut.character_field(state.player.id, "health", 100, 90, reason="test"))
    assert guard.check(state, cs) == []


def test_guard_blocks_resurrection(guard, state: WorldStateView) -> None:
    dead = state.present_characters[0]
    dead.alive = False
    cs = ChangeSet()
    cs.add(mut.character_field(dead.id, "alive", False, True, reason="revive"))
    with pytest.raises(ConsistencyViolation) as exc:
        guard.check(state, cs)
    assert exc.value.check == "alive"


def test_guard_blocks_acting_on_a_corpse(guard, state: WorldStateView) -> None:
    dead = state.present_characters[0]
    dead.alive = False
    cs = ChangeSet()
    cs.add(mut.character_move(dead.id, dead.location_id, state.player.location_id, reason="walk"))
    with pytest.raises(ConsistencyViolation):
        guard.check(state, cs)


def test_guard_blocks_dead_characters_joining_new_events(
    guard, builder: EventBuilder, state: WorldStateView
) -> None:
    """Eval 5 at the state layer: the dead do not come back for a scene."""
    dead = state.present_characters[0]
    dead.alive = False
    cs = ChangeSet()
    cs.add_event(builder.build("NPC_RETURN", actor_id=dead.id, world_minute=state.world.current_minute))
    with pytest.raises(ConsistencyViolation) as exc:
        guard.check(state, cs)
    assert exc.value.check == "alive"


def test_death_event_itself_is_allowed(guard, builder: EventBuilder, state: WorldStateView) -> None:
    victim = state.present_characters[0]
    cs = ChangeSet()
    cs.add(mut.character_death(victim.id, reason="killed"))
    cs.add_event(builder.build("DEATH", actor_id=victim.id, world_minute=state.world.current_minute))
    assert guard.check(state, cs) == []


def test_guard_blocks_teleporting_to_a_nonexistent_place(guard, state: WorldStateView) -> None:
    cs = ChangeSet()
    cs.add(mut.character_move(state.player.id, state.player.location_id, "void", reason="teleport"))
    with pytest.raises(ConsistencyViolation) as exc:
        guard.check(state, cs)
    assert exc.value.check == "location"


def test_guard_blocks_skipping_a_whole_realm(guard, state: WorldStateView, pack: ContentPack) -> None:
    ladder = pack.realms
    low = ladder.realms[0].key
    two_up = ladder.realms[2].key
    cs = ChangeSet()
    cs.add(mut.character_field(state.player.id, "realm", low, two_up, reason="cheat"))
    with pytest.raises(ConsistencyViolation) as exc:
        guard.check(state, cs)
    assert exc.value.check == "realm"


def test_guard_blocks_inventing_items(guard, state: WorldStateView) -> None:
    cs = ChangeSet()
    cs.add(mut.inventory_add(state.player.id, "sword_of_infinite_plot_armour", 1, reason="llm"))
    with pytest.raises(ConsistencyViolation) as exc:
        guard.check(state, cs)
    assert exc.value.check == "inventory"


def test_guard_blocks_time_running_backwards(guard, state: WorldStateView) -> None:
    cs = ChangeSet()
    cs.add(mut.world_time(state.world.id, 1000, 500, reason="rewind"))
    with pytest.raises(ConsistencyViolation) as exc:
        guard.check(state, cs)
    assert exc.value.check == "time"


def test_guard_blocks_out_of_range_progress(guard, state: WorldStateView) -> None:
    cs = ChangeSet()
    cs.add(mut.character_field(state.player.id, "cultivation_progress", 0.5, 4.2, reason="cheat"))
    with pytest.raises(ConsistencyViolation):
        guard.check(state, cs)


def test_non_strict_mode_collects_instead_of_raising(pack: ContentPack, state: WorldStateView) -> None:
    lenient = ConsistencyGuard(pack, strict=False)
    cs = ChangeSet()
    cs.add(mut.world_time(state.world.id, 1000, 500, reason="rewind"))
    cs.add(mut.inventory_add(state.player.id, "not_a_real_item", 1, reason="llm"))
    violations = lenient.check(state, cs)
    assert len(violations) == 2

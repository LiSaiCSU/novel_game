"""Relationship tests (Prompt sections 14, 61)."""

from __future__ import annotations

from engine.contentpack.pack import ContentPack
from engine.core.models import Relationship
from engine.core.types import ImportanceBand
from engine.relationships.manager import RelationshipManager, band_for_importance


def _rel() -> Relationship:
    return Relationship(character_a_id="a", character_b_id="b", trust=30, affection=10)


def test_ordinary_conversation_cannot_swing_trust(pack: ContentPack) -> None:
    """The headline rule: one chat must never grant +50 trust."""
    manager = RelationshipManager(pack)
    deltas, clamped = manager.clamp_deltas({"trust": 50}, ImportanceBand.TRIVIAL)
    assert deltas["trust"] <= manager.cap_for(ImportanceBand.TRIVIAL)
    assert clamped["trust"] is True


def test_life_changing_events_may_move_a_lot(pack: ContentPack) -> None:
    manager = RelationshipManager(pack)
    small, _ = manager.clamp_deltas({"trust": 40}, ImportanceBand.TRIVIAL)
    large, _ = manager.clamp_deltas({"trust": 40}, ImportanceBand.LIFE_CHANGING)
    assert large["trust"] > small["trust"]


def test_bands_scale_monotonically(pack: ContentPack) -> None:
    manager = RelationshipManager(pack)
    caps = [
        manager.cap_for(b)
        for b in (
            ImportanceBand.TRIVIAL,
            ImportanceBand.MINOR,
            ImportanceBand.MAJOR,
            ImportanceBand.LIFE_CHANGING,
        )
    ]
    assert caps == sorted(caps)


def test_importance_maps_to_a_band() -> None:
    assert band_for_importance(0.05) is ImportanceBand.TRIVIAL
    assert band_for_importance(0.4) is ImportanceBand.MINOR
    assert band_for_importance(0.7) is ImportanceBand.MAJOR
    assert band_for_importance(0.95) is ImportanceBand.LIFE_CHANGING


def test_every_change_is_audited_with_a_reason(pack: ContentPack) -> None:
    manager = RelationshipManager(pack)
    rel = _rel()
    deltas, flags = manager.clamp_deltas({"trust": 3, "suspicion": 2}, ImportanceBand.MINOR)
    updated, changes = manager.apply(
        rel, deltas, reason="rescued_from_beast", world_minute=1000, event_id="ev1"
    )
    assert len(changes) == 2
    for change in changes:
        assert change.reason == "rescued_from_beast"
        assert change.event_id == "ev1"
        assert change.world_minute == 1000
        assert change.after == change.before + change.delta
    assert updated.trust == rel.trust + deltas["trust"]
    assert updated.interaction_count == rel.interaction_count + 1
    assert flags == {"trust": False, "suspicion": False}


def test_values_stay_inside_their_range(pack: ContentPack) -> None:
    manager = RelationshipManager(pack)
    rel = Relationship(character_a_id="a", character_b_id="b", trust=99, hatred=1)
    deltas, _ = manager.clamp_deltas({"trust": 15, "hatred": -15}, ImportanceBand.MAJOR)
    updated, _ = manager.apply(rel, deltas, reason="test", world_minute=0)
    low, high = manager.bounds("trust")
    assert low <= updated.trust <= high
    assert updated.hatred >= manager.bounds("hatred")[0]


def test_unknown_dimensions_are_dropped(pack: ContentPack) -> None:
    manager = RelationshipManager(pack)
    deltas, _ = manager.clamp_deltas({"loyalty_points": 99, "trust": 1}, ImportanceBand.MINOR)
    assert set(deltas) == {"trust"}


def test_neglect_decays_a_relationship(pack: ContentPack) -> None:
    manager = RelationshipManager(pack)
    rel = Relationship(character_a_id="a", character_b_id="b", familiarity=50, affection=30)
    deltas = manager.decay(rel, months_elapsed=6)
    assert deltas["familiarity"] < 0
    assert abs(deltas["familiarity"]) <= rel.familiarity

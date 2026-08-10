"""GameRNG: reproducible, derivable, traceable (Prompt section 9)."""

from __future__ import annotations

from engine.rng.game_rng import GameRNG, event_rng, session_rng, world_rng


def test_same_seed_same_sequence() -> None:
    a = GameRNG("seed-a")
    b = GameRNG("seed-a")
    assert [a.random() for _ in range(8)] == [b.random() for _ in range(8)]


def test_different_seed_different_sequence() -> None:
    a = [GameRNG("seed-a").random() for _ in range(4)]
    b = [GameRNG("seed-b").random() for _ in range(4)]
    assert a != b


def test_derivation_is_deterministic_and_independent() -> None:
    root = world_rng("world-1")
    left = root.derive("event:alpha")
    right = world_rng("world-1").derive("event:alpha")
    assert [left.randint(0, 1000) for _ in range(5)] == [right.randint(0, 1000) for _ in range(5)]

    other = world_rng("world-1").derive("event:beta")
    assert other.seed_hex != right.seed_hex


def test_derivation_order_does_not_matter() -> None:
    """Drawing from one child stream must not disturb its sibling."""
    root = world_rng("world-1")
    a1 = root.derive("a")
    b1 = root.derive("b")
    _ = [a1.random() for _ in range(10)]
    b1_values = [b1.random() for _ in range(5)]

    fresh = world_rng("world-1").derive("b")
    assert [fresh.random() for _ in range(5)] == b1_values


def test_event_stream_is_replayable() -> None:
    first = event_rng("w", "s", "turn-7:breakthrough")
    second = event_rng("w", "s", "turn-7:breakthrough")
    assert first.chance(0.5) == second.chance(0.5)
    assert first.seed_hex == second.seed_hex


def test_traces_record_every_draw() -> None:
    rng = session_rng("w", "s")
    child = rng.derive("combat")
    child.chance(0.3)
    child.randint(1, 6)
    child.uniform(0.0, 1.0)
    assert len(rng.traces) == 3
    methods = [t.method for t in rng.traces]
    assert methods == ["chance", "randint", "uniform"]
    assert all(t.seed_hex for t in rng.traces)
    assert all(t.stream_key.startswith("world/session") for t in rng.traces)


def test_weighted_choice_respects_weights() -> None:
    rng = GameRNG("weights")
    counts = {"a": 0, "b": 0}
    for _ in range(400):
        counts[rng.weighted_choice(["a", "b"], [9, 1])] += 1
    assert counts["a"] > counts["b"] * 3


def test_chance_bounds() -> None:
    rng = GameRNG("bounds")
    assert all(rng.chance(1.0) for _ in range(20))
    assert not any(rng.chance(0.0) for _ in range(20))


def test_aggregate_distributions_are_deterministic_and_single_trace() -> None:
    first = GameRNG("temporal-jump")
    second = GameRNG("temporal-jump")
    assert first.binomial(52_000, 0.08) == second.binomial(52_000, 0.08)
    assert first.normal(100.0, 4.0) == second.normal(100.0, 4.0)
    assert [trace.method for trace in first.traces] == ["binomial", "normal"]
    assert first.traces[0].args["approximate"] is True


def test_binomial_respects_exact_bounds() -> None:
    rng = GameRNG("binomial-bounds")
    assert rng.binomial(1_000_000, 0.0) == 0
    assert rng.binomial(1_000_000, 1.0) == 1_000_000


def test_geometric_jump_is_bounded_replayable_and_traced_once() -> None:
    first = GameRNG("goal-retries")
    second = GameRNG("goal-retries")
    assert first.geometric(0.2, 100_000) == second.geometric(0.2, 100_000)
    assert first.geometric(1.0, 100_000) == 1
    assert first.geometric(0.0, 100_000) is None
    assert first.geometric(0.5, 0) is None
    assert [trace.method for trace in first.traces] == ["geometric"] * 4

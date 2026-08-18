"""The player may start a story the author never wrote - within limits.

Everything here is about the boundary: the model proposes a change of
direction, and this module decides how much of it the world is allowed to
accept. A steward that accepted everything would let one stray sentence
rewrite the game; one that accepted nothing is the freedom problem it exists
to fix.
"""

from __future__ import annotations

from dataclasses import replace

from engine.core.models import StoryClock
from engine.core.mutations import ChangeKind
from engine.core.types import ClockKind, ClockStatus, ThreadStatus
from engine.director.plot_steward import (
    MAX_NEW_THREAD_IMPORTANCE,
    PlotPlan,
    PlotSteward,
    ThreadDraft,
    ThreadRefocus,
)


def steward(pack) -> PlotSteward:
    return PlotSteward(pack)


def draft(**overrides) -> ThreadDraft:
    base = {
        "key": "thread_take_the_inn",
        "name": "盘下骡马店",
        "importance": 0.5,
        "participants": [],
        "unresolved_questions": ["周麦臣肯不肯出手"],
        "next_beat_hint": "先弄清这间店一年的流水",
    }
    return ThreadDraft(**{**base, **overrides})


def test_an_ordinary_turn_changes_nothing(pack, state) -> None:
    result = steward(pack)._validate(state, PlotPlan(direction_changed=False, new_thread=draft()))

    assert result.changes == []
    assert not result.changed_direction


def test_a_committed_player_opens_a_storyline_the_pack_never_wrote(pack, state) -> None:
    result = steward(pack)._validate(
        state, PlotPlan(direction_changed=True, new_thread=draft())
    )

    assert result.opened == ["thread_take_the_inn"]
    spawned = [c for c in result.changes if c.kind is ChangeKind.PLOT_THREAD_SPAWN]
    assert len(spawned) == 1
    assert spawned[0].payload["status"] == str(ThreadStatus.ACTIVE)
    assert spawned[0].payload["metadata"]["opened_by"] == "player"


def test_a_new_storyline_cannot_outrank_the_authored_spine(pack, state) -> None:
    result = steward(pack)._validate(
        state, PlotPlan(direction_changed=True, new_thread=draft(importance=1.0))
    )

    spawned = next(c for c in result.changes if c.kind is ChangeKind.PLOT_THREAD_SPAWN)
    assert spawned.payload["importance"] == MAX_NEW_THREAD_IMPORTANCE


def test_a_new_storyline_cannot_smuggle_in_a_cast(pack, state) -> None:
    """Opening a story is allowed; inventing the people in it is not."""
    result = steward(pack)._validate(
        state,
        PlotPlan(
            direction_changed=True,
            new_thread=draft(participants=["someone_who_does_not_exist", state.player.key]),
        ),
    )

    spawned = next(c for c in result.changes if c.kind is ChangeKind.PLOT_THREAD_SPAWN)
    assert spawned.payload["participants"] == [state.player.key]


def test_malformed_and_duplicate_keys_are_refused(pack, state) -> None:
    plot = steward(pack)
    existing = state.plot_threads[0].key

    assert plot._validate(state, PlotPlan(direction_changed=True, new_thread=draft(key="Bad Key"))).opened == []
    assert plot._validate(state, PlotPlan(direction_changed=True, new_thread=draft(key=existing))).opened == []
    assert plot._validate(state, PlotPlan(direction_changed=True, new_thread=draft(name=" "))).opened == []


def test_an_attached_clock_is_never_a_wall_clock_deadline(pack, state) -> None:
    """The engine has no basis for deciding how long a player-set goal takes."""
    result = steward(pack)._validate(
        state,
        PlotPlan(
            direction_changed=True,
            new_thread=draft(
                clock_name="盘店的进度",
                clock_kind="deadline",
                clock_segments=99,
                clock_consequence="店契到手",
            ),
        ),
    )

    clock = next(c for c in result.changes if c.kind is ChangeKind.CLOCK_SPAWN)
    assert clock.payload["minutes_per_segment"] == 0
    assert clock.payload["segments"] == 8
    assert clock.payload["thread_key"] == "thread_take_the_inn"


def test_pursuing_and_ignoring_move_a_thread_in_opposite_directions(pack, state) -> None:
    thread = state.plot_threads[0]
    before = thread.importance
    plot = steward(pack)

    up = plot._validate(
        state, PlotPlan(direction_changed=True, refocus=[ThreadRefocus(key=thread.key, intent="pursue")])
    )
    down = plot._validate(
        state, PlotPlan(direction_changed=True, refocus=[ThreadRefocus(key=thread.key, intent="ignore")])
    )

    assert up.changes[0].payload["importance"] > before
    assert down.changes[0].payload["importance"] < before


def test_abandoning_a_thread_also_stops_the_pressure_hanging_off_it(pack, state) -> None:
    thread = state.plot_threads[0]
    attached = StoryClock(
        world_id=state.world.id,
        key="clock_attached",
        name="挂在这条线上的钟",
        kind=ClockKind.PROJECT,
        thread_key=thread.key,
    )
    unrelated = StoryClock(
        world_id=state.world.id, key="clock_other", name="别的钟", kind=ClockKind.DANGER
    )
    view = replace(state, clocks=[attached, unrelated])

    result = steward(pack)._validate(
        view,
        PlotPlan(
            direction_changed=True,
            refocus=[ThreadRefocus(key=thread.key, intent="abandon", reason="玩家当众退出")],
        ),
    )

    assert result.abandoned == [thread.key]
    closed = [c for c in result.changes if c.kind is ChangeKind.CLOCK_UPDATE]
    assert len(closed) == 1
    assert closed[0].target_id == attached.id
    assert closed[0].payload["status"] == str(ClockStatus.CLOSED)


def test_a_thread_the_world_does_not_have_is_ignored(pack, state) -> None:
    result = steward(pack)._validate(
        state,
        PlotPlan(direction_changed=True, refocus=[ThreadRefocus(key="thread_invented", intent="abandon")]),
    )

    assert result.changes == []


def test_only_one_storyline_opens_per_turn(pack, state) -> None:
    """Three ambitious sentences are still one change of direction."""
    plan = PlotPlan(direction_changed=True, new_thread=draft())

    result = steward(pack)._validate(state, plan)

    assert len(result.opened) == 1

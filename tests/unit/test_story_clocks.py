"""Visible pressure: the dial, the prose and the rules read the same numbers.

A clock is the player's only way to tell an urgent turn from a spare one, so
the thing it says has to be true - both against the world clock and against
whatever the story has done to it.
"""

from __future__ import annotations

from dataclasses import replace

from engine.core.models import StoryClock
from engine.core.types import ClockKind, ClockStatus
from engine.world import clocks as clock_service


def deadline(**overrides) -> StoryClock:
    base = {
        "world_id": "w",
        "key": "clock_fuse",
        "name": "九日引信",
        "kind": ClockKind.DEADLINE,
        "segments": 9,
        "minutes_per_segment": 1440,
        "started_at_minute": 0,
    }
    return StoryClock(**{**base, **overrides})


def danger(**overrides) -> StoryClock:
    base = {
        "world_id": "w",
        "key": "clock_watch",
        "name": "被盯上",
        "kind": ClockKind.DANGER,
        "segments": 4,
    }
    return StoryClock(**{**base, **overrides})


def test_a_deadline_fills_on_the_world_clock_without_anyone_touching_it() -> None:
    clock = deadline()

    assert clock.filled_at(0) == 0
    assert clock.filled_at(1440 * 3) == 3
    assert clock.filled_at(1440 * 9) == 9
    assert clock.is_complete(1440 * 9)


def test_a_deadline_never_reports_past_its_own_last_segment() -> None:
    clock = deadline()

    assert clock.filled_at(1440 * 40) == 9


def test_remaining_time_counts_down_within_the_current_segment() -> None:
    clock = deadline()

    assert clock.remaining_minutes(0) == 1440 * 9
    # Half a day into the first segment, half a day less remains.
    assert clock.remaining_minutes(720) == 1440 * 9 - 720
    assert clock.remaining_minutes(1440 * 9) == 0


def test_an_event_driven_clock_does_not_move_with_time(state) -> None:
    clock = danger()

    assert clock.filled_at(state.world.current_minute + 100_000) == 0
    assert clock.remaining_minutes(state.world.current_minute) is None


def test_advancing_a_clock_emits_one_change_and_stops_at_full(state) -> None:
    clock = danger(filled=3)
    view = replace(state, clocks=[clock])

    changes = clock_service.advance(clock, view, 1, "caught_lying")
    assert [change.payload["filled"] for change in changes] == [4]
    assert changes[0].payload["status"] == str(ClockStatus.FILLED)

    clock.filled = 4
    assert clock_service.advance(clock, view, 1, "again") == []


def test_a_filled_deadline_is_marked_once_time_runs_out(state) -> None:
    clock = deadline(started_at_minute=state.world.current_minute)
    view = replace(state, clocks=[clock])

    assert clock_service.tick_completed(view) == []

    later = replace(
        view,
        world=view.world.model_copy(
            update={"current_minute": state.world.current_minute + 1440 * 9}
        ),
    )
    marked = clock_service.tick_completed(later)
    assert [change.payload["status"] for change in marked] == [str(ClockStatus.FILLED)]


def test_time_already_spent_caps_what_an_event_can_add(state) -> None:
    """A deadline six days gone has three segments left, not nine."""
    clock = deadline(started_at_minute=state.world.current_minute)
    later = replace(
        state,
        clocks=[clock],
        world=state.world.model_copy(
            update={"current_minute": state.world.current_minute + 1440 * 6}
        ),
    )

    changes = clock_service.advance(clock, later, 9, "someone_hurried_it_along")

    assert changes[0].payload["filled"] == 3
    assert clock.filled_at(later.world.current_minute) == 6


def test_closed_clocks_leave_the_player_view(state) -> None:
    running = danger()
    defused = danger(key="clock_defused", status=ClockStatus.CLOSED)
    hidden = danger(key="clock_hidden", visible=False)
    view = replace(state, clocks=[running, defused, hidden])

    assert [clock.key for clock in clock_service.visible_clocks(view)] == ["clock_watch"]


def test_deadlines_are_listed_before_dangers_and_projects(state) -> None:
    view = replace(
        state,
        clocks=[
            danger(key="c_project", kind=ClockKind.PROJECT),
            danger(key="c_danger"),
            deadline(key="c_deadline"),
        ],
    )

    assert [clock.key for clock in clock_service.visible_clocks(view)] == [
        "c_deadline",
        "c_danger",
        "c_project",
    ]


def test_the_prompt_view_reports_the_same_numbers_as_the_player_view(state) -> None:
    view = replace(state, clocks=[deadline(started_at_minute=state.world.current_minute)])

    rendered = clock_service.clocks_for_prompt(view)
    payload = clock_service.clock_views(view)

    assert payload[0]["filled"] == 0
    assert payload[0]["segments"] == 9
    assert "0/9" in rendered

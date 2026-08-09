"""World time (Prompt section 33)."""

from __future__ import annotations

from engine.contentpack.pack import ContentPack
from engine.world.clock import WorldClock


def test_start_time_matches_calendar(pack: ContentPack) -> None:
    clock = WorldClock(pack.calendar)
    wt = clock.to_world_time(clock.start_minute)
    assert wt.year == pack.calendar["start_year"]
    assert wt.month == pack.calendar["start_month"]
    assert wt.day == pack.calendar["start_day"]
    assert wt.hour == pack.calendar["start_hour"]
    assert wt.label


def test_advance_is_monotonic(pack: ContentPack) -> None:
    clock = WorldClock(pack.calendar)
    now = clock.start_minute
    later = clock.advance(now, 90)
    assert later == now + 90
    assert clock.to_world_time(later).minute_of_epoch > clock.to_world_time(now).minute_of_epoch


def test_day_rolls_over(pack: ContentPack) -> None:
    clock = WorldClock(pack.calendar)
    start = clock.to_world_time(clock.start_minute)
    next_day = clock.to_world_time(clock.start_minute + clock.minutes_per_day)
    assert next_day.day == start.day + 1
    assert next_day.hour == start.hour


def test_three_years_of_seclusion_moves_the_calendar(pack: ContentPack) -> None:
    clock = WorldClock(pack.calendar)
    before = clock.to_world_time(clock.start_minute)
    after = clock.to_world_time(clock.start_minute + clock.to_minutes(years=3))
    assert after.year == before.year + 3


def test_phase_and_hour_labels_cover_the_day(pack: ContentPack) -> None:
    clock = WorldClock(pack.calendar)
    phases = set()
    labels = set()
    for hour in range(clock.hours_per_day):
        wt = clock.to_world_time(clock.start_minute - clock.start_minute % clock.minutes_per_day + hour * 60)
        phases.add(wt.phase_key)
        labels.add(wt.hour_label)
    assert len(phases) >= 5
    assert len(labels) >= 10  # the twelve two-hour periods, minus rounding overlap


def test_duration_parts_picks_the_largest_unit(pack: ContentPack) -> None:
    clock = WorldClock(pack.calendar)
    assert clock.duration_parts(30)[0] == "minute"
    assert clock.duration_parts(60 * 5)[0] == "hour"
    assert clock.duration_parts(clock.minutes_per_day * 3)[0] == "day"
    assert clock.duration_parts(clock.minutes_per_month * 2)[0] == "month"
    assert clock.duration_parts(clock.minutes_per_year * 4)[0] == "year"

"""World time (Prompt section 33).

Internally the world is one integer: minutes since the epoch. Years, months,
day phases and the local hour-naming scheme all come from the content pack's
calendar, so a sci-fi pack can ship a completely different calendar without
touching this file (DECISIONS D-005).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WorldTime:
    minute_of_epoch: int
    year: int
    month: int
    day: int
    hour: int
    minute: int
    phase_key: str
    phase_name: str
    hour_label: str
    season_key: str
    label: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "minute_of_epoch": self.minute_of_epoch,
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "hour": self.hour,
            #: The UI shows a wall clock, so the minute has to reach it too.
            "minute": self.minute,
            "phase": self.phase_key,
            "phase_name": self.phase_name,
            "hour_label": self.hour_label,
            "season": self.season_key,
            "label": self.label,
        }


class WorldClock:
    def __init__(self, calendar: dict[str, Any]) -> None:
        self.cal = calendar
        self.minutes_per_hour: int = int(calendar.get("minutes_per_hour", 60))
        self.hours_per_day: int = int(calendar.get("hours_per_day", 24))
        self.days_per_month: int = int(calendar.get("days_per_month", 30))
        self.months_per_year: int = int(calendar.get("months_per_year", 12))
        self.minutes_per_day = self.minutes_per_hour * self.hours_per_day
        self.minutes_per_month = self.minutes_per_day * self.days_per_month
        self.minutes_per_year = self.minutes_per_month * self.months_per_year
        self._start_offset = self._compute_start_offset()

    def _compute_start_offset(self) -> int:
        cal = self.cal
        year = int(cal.get("start_year", 1)) - int(cal.get("epoch_year", 1))
        month = int(cal.get("start_month", 1)) - 1
        day = int(cal.get("start_day", 1)) - 1
        hour = int(cal.get("start_hour", 0))
        minute = int(cal.get("start_minute", 0))
        return (
            year * self.minutes_per_year
            + month * self.minutes_per_month
            + day * self.minutes_per_day
            + hour * self.minutes_per_hour
            + minute
        )

    @property
    def start_minute(self) -> int:
        """The world_minute value corresponding to the pack's declared start date."""
        return self._start_offset

    # -- conversion ---------------------------------------------------------
    def to_world_time(self, world_minute: int) -> WorldTime:
        total = max(0, int(world_minute))
        year, rem = divmod(total, self.minutes_per_year)
        month, rem = divmod(rem, self.minutes_per_month)
        day, rem = divmod(rem, self.minutes_per_day)
        hour, minute = divmod(rem, self.minutes_per_hour)

        year_display = year + int(self.cal.get("epoch_year", 1))
        month_display = month + 1
        day_display = day + 1

        phase_key, phase_name = self._phase(hour)
        hour_label = self._hour_label(hour)
        season_key = self._season(month_display)
        label = self._format(year_display, month_display, day_display, hour_label, phase_name)

        return WorldTime(
            minute_of_epoch=total,
            year=year_display,
            month=month_display,
            day=day_display,
            hour=hour,
            minute=minute,
            phase_key=phase_key,
            phase_name=phase_name,
            hour_label=hour_label,
            season_key=season_key,
            label=label,
        )

    def _phase(self, hour: int) -> tuple[str, str]:
        for phase in self.cal.get("day_phases", []):
            start, end = int(phase["start_hour"]), int(phase["end_hour"])
            if start <= hour < end:
                return str(phase["key"]), str(phase.get("name", phase["key"]))
        return "day", "day"

    def _hour_label(self, hour: int) -> str:
        for entry in self.cal.get("shichen", []):
            start, end = int(entry["start_hour"]), int(entry["end_hour"])
            if start <= end:
                if start <= hour < end:
                    return str(entry.get("name", entry["key"]))
            elif hour >= start or hour < end:  # wraps past midnight
                return str(entry.get("name", entry["key"]))
        return f"{hour:02d}:00"

    def _season(self, month_display: int) -> str:
        for season in self.cal.get("seasons", []):
            if month_display in season.get("months", []):
                return str(season["key"])
        return "none"

    def _format(self, year: int, month: int, day: int, hour_label: str, phase_name: str) -> str:
        month_names = self.cal.get("month_names") or []
        month_name = month_names[month - 1] if 0 < month <= len(month_names) else str(month)
        template = str(self.cal.get("format", "{year}-{month}-{day} {hour_label}"))
        return template.format(
            epoch_label=self.cal.get("epoch_label", ""),
            year=year,
            month=month,
            month_name=month_name,
            day=day,
            shichen=hour_label,
            hour_label=hour_label,
            phase=phase_name,
        )

    # -- arithmetic ---------------------------------------------------------
    def advance(self, world_minute: int, minutes: int) -> int:
        return max(0, int(world_minute) + max(0, int(minutes)))

    def days_between(self, a: int, b: int) -> float:
        return abs(b - a) / self.minutes_per_day

    def to_minutes(self, *, years: int = 0, months: int = 0, days: int = 0, hours: int = 0) -> int:
        return (
            years * self.minutes_per_year
            + months * self.minutes_per_month
            + days * self.minutes_per_day
            + hours * self.minutes_per_hour
        )

    def duration_parts(self, minutes: int) -> tuple[str, int]:
        """Largest sensible display unit for a span, as ``(unit_key, count)``.

        Unit keys match the ``duration`` block of the pack's narrative
        templates, so the wording stays in content.
        """
        minutes = max(0, int(minutes))
        if minutes >= self.minutes_per_year:
            return "year", minutes // self.minutes_per_year
        if minutes >= self.minutes_per_month:
            return "month", minutes // self.minutes_per_month
        if minutes >= self.minutes_per_day:
            return "day", minutes // self.minutes_per_day
        if minutes >= self.minutes_per_hour * 2:
            return "hour", minutes // (self.minutes_per_hour * 2)
        return "minute", max(1, minutes // 15)

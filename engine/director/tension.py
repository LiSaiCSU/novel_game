"""Narrative tension (Prompt section 25).

Tension is a wave, not a staircase. It rises with consequential events and
decays with quiet time, and the Director is forbidden from holding it at the
top (see :func:`must_de_escalate`).
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.contentpack.pack import ContentPack


@dataclass(frozen=True, slots=True)
class TensionBand:
    key: str
    name: str
    low: float
    high: float


class TensionModel:
    def __init__(self, pack: ContentPack) -> None:
        self.pack = pack
        self.decay_per_day = float(pack.rule("narrative.tension_decay_per_day", 2.0))
        self.gain_scale = float(pack.rule("narrative.tension_gain_by_importance", 30.0))
        # Below this, an event is bookkeeping rather than drama. Without a
        # floor every step - including walking from one room to the next -
        # ratcheted tension upward, so a quiet fortnight of errands ended at
        # the same pitch as a murder.
        self.gain_floor = float(pack.rule("narrative.tension_gain_floor", 0.12))
        self.high_threshold = float(pack.rule("narrative.high_threshold", 75.0))
        self.max_consecutive_high = int(pack.rule("narrative.max_consecutive_high_turns", 3))
        self.bands = [
            TensionBand(
                key=str(b["key"]),
                name=str(b.get("name", b["key"])),
                low=float(b["min"]),
                high=float(b["max"]),
            )
            for b in (pack.rule("narrative.bands", []) or [])
        ]

    # ------------------------------------------------------------------
    def band(self, value: float) -> TensionBand:
        for band in self.bands:
            if band.low <= value < band.high:
                return band
        return self.bands[-1] if self.bands else TensionBand("unknown", "unknown", 0, 100)

    def decay(self, current: float, days_elapsed: float) -> float:
        return _clamp(current - self.decay_per_day * max(0.0, days_elapsed))

    def gain(self, current: float, importance: float) -> float:
        notable = max(0.0, importance - self.gain_floor)
        return _clamp(current + notable * self.gain_scale)

    def apply(self, current: float, *, days_elapsed: float, importance: float) -> float:
        return self.gain(self.decay(current, days_elapsed), importance)

    # ------------------------------------------------------------------
    def must_de_escalate(self, history: list[float], current: float) -> bool:
        """True when the story has been at a climax for too long.

        Prompt section 25 bans climax-climax-climax-climax; this is where that
        ban is enforced in code rather than hoped for in a prompt.
        """
        recent = ([*history, current])[-self.max_consecutive_high :]
        if len(recent) < self.max_consecutive_high:
            return False
        return all(value >= self.high_threshold for value in recent)

    def describe(self, value: float, history: list[float]) -> dict[str, object]:
        band = self.band(value)
        return {
            "value": round(value, 1),
            "band": band.key,
            "band_name": band.name,
            "history": [round(v, 1) for v in history[-8:]],
            "must_de_escalate": self.must_de_escalate(history, value),
        }


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))

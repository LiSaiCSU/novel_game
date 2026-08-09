"""Shared test doubles."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from engine.rng.game_rng import GameRNG

T = TypeVar("T")


class RiggedRNG(GameRNG):
    """A GameRNG whose coin flips are pinned.

    GameRNG uses ``__slots__`` precisely so nobody can bolt state onto a live
    stream; subclassing is the sanctioned way to force an outcome in a test.
    """

    def __init__(
        self,
        seed_material: str = "rigged",
        *,
        chance_result: bool = True,
        stream_key: str = "rigged",
    ) -> None:
        super().__init__(seed_material, stream_key=stream_key)
        self.chance_result = chance_result

    def chance(self, probability: float) -> bool:
        self._record("chance", {"p": probability, "forced": True}, self.chance_result)
        return self.chance_result


class SequenceRNG(GameRNG):
    """Returns a scripted list of chance() outcomes, then falls back to real rolls."""

    def __init__(self, results: Sequence[bool], seed_material: str = "scripted") -> None:
        super().__init__(seed_material, stream_key="scripted")
        self.results = list(results)

    def chance(self, probability: float) -> bool:
        if self.results:
            outcome = self.results.pop(0)
            self._record("chance", {"p": probability, "forced": True}, outcome)
            return outcome
        return super().chance(probability)

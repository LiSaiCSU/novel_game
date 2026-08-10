"""Deterministic, traceable randomness (Prompt section 9).

Rules:

* Nobody calls ``random`` directly. Everything goes through :class:`GameRNG`.
* Seeds are derived, never invented: ``world_seed -> session_seed -> event_key``.
* Every draw is recorded as an :class:`RngTrace` so a turn can be replayed and
  explained after the fact.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class RngTrace(BaseModel):
    stream_key: str
    seed_hex: str
    method: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: Any = None


def _seed_int(material: str) -> tuple[int, str]:
    digest = hashlib.blake2b(material.encode("utf-8"), digest_size=16).hexdigest()
    return int(digest, 16), digest


class GameRNG:
    """A named random stream.

    ``derive()`` produces a child stream whose sequence depends only on the
    seed material, so the same world + session + event key always yields the
    same numbers regardless of call ordering elsewhere.
    """

    __slots__ = ("_material", "_rng", "_seed_hex", "_traces", "stream_key")

    def __init__(self, seed_material: str, *, stream_key: str = "root") -> None:
        seed_int, seed_hex = _seed_int(seed_material)
        self._material = seed_material
        self._seed_hex = seed_hex
        self._rng = random.Random(seed_int)
        self._traces: list[RngTrace] = []
        self.stream_key = stream_key

    # -- derivation ---------------------------------------------------------
    def derive(self, key: str) -> GameRNG:
        child = GameRNG(f"{self._material}|{key}", stream_key=f"{self.stream_key}/{key}")
        child._traces = self._traces  # children share the parent's trace log
        return child

    @property
    def seed_hex(self) -> str:
        return self._seed_hex

    @property
    def traces(self) -> list[RngTrace]:
        return self._traces

    def _record(self, method: str, args: dict[str, Any], result: Any) -> None:
        self._traces.append(
            RngTrace(
                stream_key=self.stream_key,
                seed_hex=self._seed_hex,
                method=method,
                args=args,
                result=result,
            )
        )

    # -- draws --------------------------------------------------------------
    def random(self) -> float:
        value = self._rng.random()
        self._record("random", {}, value)
        return value

    def uniform(self, low: float, high: float) -> float:
        value = self._rng.uniform(low, high)
        self._record("uniform", {"low": low, "high": high}, value)
        return value

    def normal(self, mean: float, stddev: float) -> float:
        """One traceable draw from a normal distribution."""
        stddev = max(0.0, float(stddev))
        value = self._rng.gauss(float(mean), stddev) if stddev else float(mean)
        self._record("normal", {"mean": mean, "stddev": stddev}, value)
        return value

    def binomial(self, trials: int, probability: float) -> int:
        """Bounded-cost aggregate Bernoulli sampling.

        Small populations use exact draws. Large populations use bounded-cost
        Poisson/normal approximations, so a temporal jump over decades consumes
        one traced aggregate operation rather than one draw per week.
        """
        trials = max(0, int(trials))
        probability = max(0.0, min(1.0, float(probability)))
        mean = trials * probability
        inverse_mean = trials * (1.0 - probability)
        approximate = trials >= 128

        if trials == 0 or probability == 0.0:
            value = 0
        elif probability == 1.0:
            value = trials
        elif approximate:
            if mean < 30.0:
                value = self._poisson_approximation(mean)
            elif inverse_mean < 30.0:
                value = trials - self._poisson_approximation(inverse_mean)
            else:
                stddev = math.sqrt(trials * probability * (1.0 - probability))
                value = round(self._rng.gauss(mean, stddev))
            value = max(0, min(trials, value))
        else:
            value = sum(1 for _ in range(trials) if self._rng.random() < probability)
        self._record(
            "binomial",
            {"trials": trials, "p": probability, "approximate": approximate},
            value,
        )
        return value

    def geometric(self, probability: float, max_trials: int) -> int | None:
        """Sample the first successful trial in bounded constant time.

        ``None`` means that all available trials failed.  Temporal systems use
        this to jump directly across repeated attempts instead of replaying one
        attempt per day or week.
        """
        probability = max(0.0, min(1.0, float(probability)))
        max_trials = max(0, int(max_trials))
        roll = self._rng.random() if probability > 0.0 and max_trials > 0 else 1.0
        if probability <= 0.0 or max_trials <= 0:
            value = None
        elif probability >= 1.0:
            value = 1
        else:
            trial = math.floor(math.log1p(-roll) / math.log1p(-probability)) + 1
            value = trial if trial <= max_trials else None
        self._record(
            "geometric",
            {"p": probability, "max_trials": max_trials, "roll": roll},
            value,
        )
        return value

    def _poisson_approximation(self, mean: float) -> int:
        threshold = math.exp(-mean)
        product = 1.0
        count = 0
        while product > threshold:
            count += 1
            product *= self._rng.random()
        return count - 1

    def randint(self, low: int, high: int) -> int:
        value = self._rng.randint(low, high)
        self._record("randint", {"low": low, "high": high}, value)
        return value

    def chance(self, probability: float) -> bool:
        roll = self._rng.random()
        outcome = roll < probability
        self._record("chance", {"p": probability, "roll": roll}, outcome)
        return outcome

    def choice(self, options: Sequence[T]) -> T:
        if not options:
            raise ValueError("choice() from an empty sequence")
        index = self._rng.randrange(len(options))
        value = options[index]
        self._record("choice", {"n": len(options), "index": index}, repr(value))
        return value

    def weighted_choice(self, options: Sequence[T], weights: Sequence[float]) -> T:
        if not options:
            raise ValueError("weighted_choice() from an empty sequence")
        if len(options) != len(weights):
            raise ValueError("options and weights must be the same length")
        total = float(sum(weights))
        if total <= 0:
            return self.choice(options)
        roll = self._rng.random() * total
        acc = 0.0
        for option, weight in zip(options, weights, strict=True):
            acc += float(weight)
            if roll <= acc:
                self._record(
                    "weighted_choice", {"n": len(options), "roll": roll, "total": total}, repr(option)
                )
                return option
        return options[-1]

    def sample(self, options: Sequence[T], k: int) -> list[T]:
        k = max(0, min(k, len(options)))
        values = self._rng.sample(list(options), k)
        self._record("sample", {"n": len(options), "k": k}, [repr(v) for v in values])
        return values

    def shuffled(self, options: Sequence[T]) -> list[T]:
        values = list(options)
        self._rng.shuffle(values)
        self._record("shuffled", {"n": len(values)}, None)
        return values


def world_rng(world_seed: str) -> GameRNG:
    return GameRNG(world_seed, stream_key="world")


def session_rng(world_seed: str, session_seed: str) -> GameRNG:
    return GameRNG(world_seed, stream_key="world").derive(f"session:{session_seed}")


def event_rng(world_seed: str, session_seed: str, event_key: str) -> GameRNG:
    return session_rng(world_seed, session_seed).derive(f"event:{event_key}")

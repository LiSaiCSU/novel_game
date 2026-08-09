"""Deterministic, traceable randomness (Prompt section 9).

Rules:

* Nobody calls ``random`` directly. Everything goes through :class:`GameRNG`.
* Seeds are derived, never invented: ``world_seed -> session_seed -> event_key``.
* Every draw is recorded as an :class:`RngTrace` so a turn can be replayed and
  explained after the fact.
"""

from __future__ import annotations

import hashlib
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

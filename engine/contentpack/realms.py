"""The progression ladder, read entirely from content.

The engine has no idea what a "realm" is called or how many exist. Adding tiers
to ``realms.yaml`` extends the game without touching Python (Prompt section 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.core.errors import ContentValidationError


@dataclass(frozen=True, slots=True)
class Stage:
    key: str
    name: str
    order: int


@dataclass(frozen=True, slots=True)
class Realm:
    key: str
    name: str
    order: int
    stages: tuple[Stage, ...]
    power_coefficient: float
    power_per_stage: float
    max_health: int
    max_spiritual_power: int
    health_per_stage: int
    spiritual_power_per_stage: int
    lifespan_years: int
    xp_to_next_stage: int
    breakthrough_base_chance: float
    description: str
    playable: bool


class RealmLadder:
    def __init__(self, raw: dict[str, Any]) -> None:
        realms: list[Realm] = []
        for entry in raw.get("realms", []):
            stages = tuple(
                Stage(key=s["key"], name=s.get("name", ""), order=int(s.get("order", i)))
                for i, s in enumerate(entry.get("stages", [{"key": "normal", "name": "", "order": 0}]))
            )
            realms.append(
                Realm(
                    key=entry["key"],
                    name=entry.get("name", entry["key"]),
                    order=int(entry["order"]),
                    stages=stages,
                    power_coefficient=float(entry.get("power_coefficient", 1.0)),
                    power_per_stage=float(entry.get("power_per_stage", 0.0)),
                    max_health=int(entry.get("max_health", 100)),
                    max_spiritual_power=int(entry.get("max_spiritual_power", 0)),
                    health_per_stage=int(entry.get("health_per_stage", 0)),
                    spiritual_power_per_stage=int(entry.get("spiritual_power_per_stage", 0)),
                    lifespan_years=int(entry.get("lifespan_years", 70)),
                    xp_to_next_stage=int(entry.get("xp_to_next_stage", 0)),
                    breakthrough_base_chance=float(entry.get("breakthrough_base_chance", 0.3)),
                    description=entry.get("description", ""),
                    playable=bool(entry.get("playable_in_v1", True)),
                )
            )
        if not realms:
            raise ContentValidationError("realms.yaml defines no realms")
        realms.sort(key=lambda r: r.order)
        self._realms: tuple[Realm, ...] = tuple(realms)
        self._by_key: dict[str, Realm] = {r.key: r for r in realms}
        self.progression_name: str = raw.get("progression_name", "cultivation")
        self.spiritual_roots: list[dict[str, Any]] = list(raw.get("spiritual_roots", []))
        self.mental_states: list[dict[str, Any]] = list(raw.get("mental_states", []))
        self.bottleneck: dict[str, Any] = dict(raw.get("bottleneck", {}))

    # -- lookup -------------------------------------------------------------
    @property
    def realms(self) -> tuple[Realm, ...]:
        return self._realms

    def realm(self, key: str) -> Realm:
        try:
            return self._by_key[key]
        except KeyError as exc:
            raise ContentValidationError(f"unknown realm {key!r}") from exc

    def has_realm(self, key: str) -> bool:
        return key in self._by_key

    def order(self, realm_key: str) -> int:
        return self.realm(realm_key).order

    def stage(self, realm_key: str, stage_key: str) -> Stage:
        realm = self.realm(realm_key)
        for stage in realm.stages:
            if stage.key == stage_key:
                return stage
        raise ContentValidationError(f"unknown stage {stage_key!r} for realm {realm_key!r}")

    def stage_order(self, realm_key: str, stage_key: str) -> int:
        return self.stage(realm_key, stage_key).order

    def first_stage(self, realm_key: str) -> Stage:
        return self.realm(realm_key).stages[0]

    # -- comparisons --------------------------------------------------------
    def rank(self, realm_key: str, stage_key: str) -> tuple[int, int]:
        return self.order(realm_key), self.stage_order(realm_key, stage_key)

    def compare(self, realm_a: str, stage_a: str, realm_b: str, stage_b: str) -> int:
        ra, rb = self.rank(realm_a, stage_a), self.rank(realm_b, stage_b)
        return (ra > rb) - (ra < rb)

    def meets_requirement(
        self, realm_key: str, stage_key: str, required_realm: str, required_stage: str
    ) -> bool:
        return self.compare(realm_key, stage_key, required_realm, required_stage) >= 0

    def realm_gap(self, realm_a: str, realm_b: str) -> int:
        """How many whole tiers A is above B (negative means below)."""
        return self.order(realm_a) - self.order(realm_b)

    # -- derived stats ------------------------------------------------------
    def power(self, realm_key: str, stage_key: str) -> float:
        realm = self.realm(realm_key)
        return realm.power_coefficient + realm.power_per_stage * self.stage_order(
            realm_key, stage_key
        )

    def max_health(self, realm_key: str, stage_key: str) -> int:
        realm = self.realm(realm_key)
        return realm.max_health + realm.health_per_stage * self.stage_order(realm_key, stage_key)

    def max_spiritual_power(self, realm_key: str, stage_key: str) -> int:
        realm = self.realm(realm_key)
        return realm.max_spiritual_power + realm.spiritual_power_per_stage * self.stage_order(
            realm_key, stage_key
        )

    def xp_required(self, realm_key: str) -> int:
        return self.realm(realm_key).xp_to_next_stage

    # -- progression --------------------------------------------------------
    def next_step(self, realm_key: str, stage_key: str) -> tuple[str, str] | None:
        """The tier immediately above the given one, or None at the ceiling."""
        realm = self.realm(realm_key)
        idx = self.stage_order(realm_key, stage_key)
        if idx + 1 < len(realm.stages):
            return realm_key, realm.stages[idx + 1].key
        higher = [r for r in self._realms if r.order == realm.order + 1]
        if not higher:
            return None
        nxt = higher[0]
        return nxt.key, nxt.stages[0].key

    def is_realm_boundary(self, realm_key: str, stage_key: str) -> bool:
        """True when the next step crosses into a whole new realm."""
        step = self.next_step(realm_key, stage_key)
        return step is not None and step[0] != realm_key

    # -- presentation -------------------------------------------------------
    def display(self, realm_key: str, stage_key: str) -> str:
        realm = self.realm(realm_key)
        try:
            stage = self.stage(realm_key, stage_key)
        except ContentValidationError:
            return realm.name
        return f"{realm.name}{stage.name}" if stage.name else realm.name

    def spiritual_root(self, key: str) -> dict[str, Any]:
        for root in self.spiritual_roots:
            if root.get("key") == key:
                return root
        return {"key": key, "name": key, "speed": 1.0, "breakthrough_mod": 0.0}

    def mental_state_band(self, value: float) -> dict[str, Any]:
        for band in self.mental_states:
            if float(band.get("min", 0.0)) <= value < float(band.get("max", 1.0)):
                return band
        return {"key": "stable", "name": "", "breakthrough_mod": 0.0}

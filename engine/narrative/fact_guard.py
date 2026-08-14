"""Deterministic guard for author-declared prose invariants.

The model is allowed to choose wording, not to turn precise evidence back into
uncertainty. Content authors opt into narrowly scoped literal constraints on
items; the engine never learns genre-specific facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from engine.contentpack.pack import ContentPack
from engine.world.state_view import WorldStateView

_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class NarrativeFactViolation:
    item_key: str
    kind: str
    value: str

    def as_dict(self) -> dict[str, str]:
        return {"item_key": self.item_key, "kind": self.kind, "value": self.value}


class NarrativeFactGuard:
    def __init__(self, pack: ContentPack) -> None:
        self.pack = pack

    def review(
        self,
        state: WorldStateView,
        *,
        player_action: str,
        prose: str,
    ) -> list[NarrativeFactViolation]:
        compact_action = self._compact(player_action)
        compact_prose = self._compact(prose)
        violations: list[NarrativeFactViolation] = []

        for held in state.inventory:
            raw = self.pack.item(held.item_key)
            if raw is None:
                continue
            constraints = (raw.get("metadata") or {}).get("narrative_constraints") or {}
            if not isinstance(constraints, dict):
                continue
            aliases = [str(raw.get("name") or held.item_key)]
            aliases.extend(str(value) for value in constraints.get("aliases", []) or [])
            if not any(self._compact(alias) in compact_action for alias in aliases if alias):
                continue

            for required in constraints.get("required_when_referenced", []) or []:
                value = str(required).strip()
                if value and self._compact(value) not in compact_prose:
                    violations.append(
                        NarrativeFactViolation(held.item_key, "missing_required", value)
                    )
            for forbidden in constraints.get("forbidden_when_referenced", []) or []:
                value = str(forbidden).strip()
                if value and self._compact(value) in compact_prose:
                    violations.append(
                        NarrativeFactViolation(held.item_key, "forbidden_present", value)
                    )
        return violations

    @staticmethod
    def _compact(value: str) -> str:
        return _SPACE.sub("", value).casefold()

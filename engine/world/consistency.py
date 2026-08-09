"""ConsistencyGuard - the last gate before commit (Prompt section 63).

Program checks run before any AI critic. A violation here is an engine bug, not
a game outcome: the turn is rolled back and the violation is recorded.
"""

from __future__ import annotations

from typing import Any

from engine.contentpack.pack import ContentPack
from engine.core.errors import ConsistencyViolation
from engine.core.models import Character
from engine.core.mutations import ChangeKind, ChangeSet, StateChange
from engine.world.state_view import WorldStateView


class ConsistencyGuard:
    def __init__(self, pack: ContentPack, *, strict: bool | None = None) -> None:
        self.pack = pack
        self.strict = (
            bool(pack.rule("consistency.strict", True)) if strict is None else strict
        )
        self.enabled_checks: set[str] = set(
            pack.rule("consistency.checks", [])
            or ["alive", "location", "inventory", "realm", "knowledge", "faction", "time"]
        )

    def check(
        self,
        state: WorldStateView,
        change_set: ChangeSet,
        *,
        characters: dict[str, Character] | None = None,
    ) -> list[dict[str, Any]]:
        """Returns a list of violations. Raises in strict mode."""
        known: dict[str, Character] = dict(characters or {})
        known.setdefault(state.player.id, state.player)
        for c in state.present_characters:
            known.setdefault(c.id, c)

        violations: list[dict[str, Any]] = []
        dying: set[str] = {
            c.target_id for c in change_set.by_kind(ChangeKind.CHARACTER_DEATH)
        }
        already_dead: set[str] = {cid for cid, ch in known.items() if not ch.alive}

        for change in change_set.changes:
            if "alive" in self.enabled_checks:
                violations += self._check_alive(change, known, already_dead)
            if "location" in self.enabled_checks:
                violations += self._check_location(change, state)
            if "realm" in self.enabled_checks:
                violations += self._check_realm(change)
            if "inventory" in self.enabled_checks:
                violations += self._check_inventory(change)
            if "time" in self.enabled_checks:
                violations += self._check_time(change, state)

        if "alive" in self.enabled_checks:
            for event in change_set.events:
                participants = set(event.target_ids) | ({event.actor_id} if event.actor_id else set())
                # A death event legitimately involves the character who just died.
                participants -= dying
                for pid in participants:
                    if pid in already_dead:
                        violations.append(
                            {
                                "check": "alive",
                                "message": "a dead character cannot participate in a new event",
                                "character_id": pid,
                                "event_type": event.event_type,
                            }
                        )

        if "knowledge" in self.enabled_checks:
            violations += self._check_knowledge(change_set)

        if violations and self.strict:
            first = violations[0]
            raise ConsistencyViolation(
                str(first["check"]), str(first["message"]), violations=violations
            )
        return violations

    # ------------------------------------------------------------------
    def _check_alive(
        self, change: StateChange, known: dict[str, Character], already_dead: set[str]
    ) -> list[dict[str, Any]]:
        if change.kind is ChangeKind.CHARACTER_DEATH:
            return []
        if change.kind not in (
            ChangeKind.CHARACTER_FIELD,
            ChangeKind.CHARACTER_LOCATION,
            ChangeKind.CHARACTER_EMOTION,
            ChangeKind.SKILL_LEARN,
            ChangeKind.SKILL_USED,
        ):
            return []
        if change.target_id in already_dead:
            # Corpses may still be looted, but they do not act.
            return [
                {
                    "check": "alive",
                    "message": "cannot mutate a dead character",
                    "character_id": change.target_id,
                    "change": change.describe(),
                }
            ]
        if change.kind is ChangeKind.CHARACTER_FIELD and change.field == "alive" and change.after:
            return [
                {
                    "check": "alive",
                    "message": "resurrection is not permitted",
                    "character_id": change.target_id,
                }
            ]
        return []

    def _check_location(self, change: StateChange, state: WorldStateView) -> list[dict[str, Any]]:
        if change.kind is not ChangeKind.CHARACTER_LOCATION:
            return []
        destination = state.graph.by_id(str(change.after))
        if destination is None:
            return [
                {
                    "check": "location",
                    "message": "destination does not exist",
                    "location_id": change.after,
                }
            ]
        origin = state.graph.by_id(str(change.before)) if change.before else None
        if origin is not None and state.graph.path(origin.key, destination.key) is None:
            return [
                {
                    "check": "location",
                    "message": "no route between origin and destination",
                    "from": origin.key,
                    "to": destination.key,
                }
            ]
        return []

    def _check_realm(self, change: StateChange) -> list[dict[str, Any]]:
        if change.kind is not ChangeKind.CHARACTER_FIELD:
            return []
        ladder = self.pack.realms
        if change.field == "realm":
            if not ladder.has_realm(str(change.after)):
                return [
                    {"check": "realm", "message": "unknown realm", "value": change.after}
                ]
            before, after = str(change.before), str(change.after)
            if ladder.has_realm(before) and ladder.order(after) - ladder.order(before) > 1:
                return [
                    {
                        "check": "realm",
                        "message": "cannot skip a whole tier in one step",
                        "from": before,
                        "to": after,
                    }
                ]
        if change.field == "cultivation_progress":
            value = float(change.after)
            if value < 0.0 or value > 1.0:
                return [
                    {"check": "realm", "message": "cultivation progress out of range", "value": value}
                ]
        return []

    def _check_inventory(self, change: StateChange) -> list[dict[str, Any]]:
        if change.kind not in (ChangeKind.INVENTORY_ADD, ChangeKind.INVENTORY_REMOVE):
            return []
        item_key = str(change.payload.get("item_key", ""))
        quantity = int(change.payload.get("quantity", 0))
        problems: list[dict[str, Any]] = []
        if self.pack.item(item_key) is None:
            problems.append(
                {
                    "check": "inventory",
                    "message": "item does not exist in the content pack",
                    "item_key": item_key,
                }
            )
        if quantity <= 0:
            problems.append(
                {"check": "inventory", "message": "quantity must be positive", "quantity": quantity}
            )
        return problems

    def _check_time(self, change: StateChange, state: WorldStateView) -> list[dict[str, Any]]:
        if change.kind is not ChangeKind.WORLD_TIME:
            return []
        before, after = int(change.before), int(change.after)
        if after < before:
            return [
                {"check": "time", "message": "world time cannot move backwards", "from": before, "to": after}
            ]
        return []

    def _check_knowledge(self, change_set: ChangeSet) -> list[dict[str, Any]]:
        problems: list[dict[str, Any]] = []
        for change in change_set.by_kind(ChangeKind.KNOWLEDGE_SET):
            confidence = float(change.payload.get("confidence", 0.0))
            if not 0.0 <= confidence <= 1.0:
                problems.append(
                    {
                        "check": "knowledge",
                        "message": "confidence out of range",
                        "confidence": confidence,
                    }
                )
            if not change.payload.get("fact_id"):
                problems.append(
                    {"check": "knowledge", "message": "knowledge change without a fact id"}
                )
        return problems

"""Relationship arithmetic (Prompt section 14).

Eight dimensions, not one affection bar. Every movement is clamped by the
importance of its cause and written to an audit row, so "one chat gave +50
trust" is structurally impossible rather than merely discouraged.
"""

from __future__ import annotations

from engine.contentpack.pack import ContentPack
from engine.core.models import RELATIONSHIP_DIMENSIONS, Relationship, RelationshipChange
from engine.core.mutations import StateChange, relationship_delta
from engine.core.types import ImportanceBand


def band_for_importance(importance: float) -> ImportanceBand:
    if importance >= 0.9:
        return ImportanceBand.LIFE_CHANGING
    if importance >= 0.6:
        return ImportanceBand.MAJOR
    if importance >= 0.3:
        return ImportanceBand.MINOR
    return ImportanceBand.TRIVIAL


class RelationshipManager:
    def __init__(self, pack: ContentPack) -> None:
        self.pack = pack
        self._ranges: dict[str, dict[str, int]] = pack.rule("relationship.ranges", {}) or {}
        self._caps: dict[str, int] = pack.rule("relationship.max_delta_per_event", {}) or {}

    # ------------------------------------------------------------------
    def cap_for(self, band: ImportanceBand) -> int:
        return int(self._caps.get(str(band), 2))

    def bounds(self, dimension: str) -> tuple[int, int]:
        spec = self._ranges.get(dimension, {})
        return int(spec.get("min", -100)), int(spec.get("max", 100))

    def clamp_deltas(
        self, deltas: dict[str, int | float], band: ImportanceBand
    ) -> tuple[dict[str, int], dict[str, bool]]:
        """Clip a proposal to what an event of this magnitude may do."""
        cap = self.cap_for(band)
        clean: dict[str, int] = {}
        clamped: dict[str, bool] = {}
        for dim, raw in (deltas or {}).items():
            if dim not in RELATIONSHIP_DIMENSIONS:
                continue
            try:
                value = round(float(raw))
            except (TypeError, ValueError):
                continue
            if value == 0:
                continue
            limited = max(-cap, min(cap, value))
            clean[dim] = limited
            clamped[dim] = limited != value
        return clean, clamped

    def apply(
        self,
        relationship: Relationship,
        deltas: dict[str, int],
        *,
        reason: str,
        world_minute: int,
        event_id: str | None = None,
        clamped_flags: dict[str, bool] | None = None,
    ) -> tuple[Relationship, list[RelationshipChange]]:
        """Return an updated copy plus one audit row per moved dimension."""
        clamped_flags = clamped_flags or {}
        changes: list[RelationshipChange] = []
        updated = relationship.model_copy(deep=True)
        for dim, delta in deltas.items():
            low, high = self.bounds(dim)
            before = int(getattr(updated, dim))
            after = max(low, min(high, before + delta))
            if after == before:
                continue
            setattr(updated, dim, after)
            changes.append(
                RelationshipChange(
                    world_id=relationship.world_id,
                    character_a_id=relationship.character_a_id,
                    character_b_id=relationship.character_b_id,
                    dimension=dim,
                    before=before,
                    after=after,
                    delta=after - before,
                    reason=reason,
                    event_id=event_id,
                    clamped=bool(clamped_flags.get(dim, False)),
                    world_minute=world_minute,
                )
            )
        updated.last_interaction_minute = world_minute
        updated.interaction_count += 1
        return updated, changes

    # ------------------------------------------------------------------
    def interaction_deltas(
        self, *, familiarity_gain: int | None = None, extra: dict[str, int] | None = None
    ) -> dict[str, int]:
        """Baseline drift from simply having interacted."""
        gain = (
            familiarity_gain
            if familiarity_gain is not None
            else int(self.pack.rule("relationship.familiarity_gain_per_interaction", 1))
        )
        deltas = {"familiarity": gain} if gain else {}
        if extra:
            deltas.update(extra)
        return deltas

    def to_state_change(
        self, a_id: str, b_id: str, deltas: dict[str, int], reason: str
    ) -> StateChange:
        return relationship_delta(a_id, b_id, deltas, reason)

    def decay(self, relationship: Relationship, months_elapsed: float) -> dict[str, int]:
        """Slow drift when two people stop meeting."""
        if months_elapsed <= 0:
            return {}
        spec = self.pack.rule("relationship.decay_per_month_without_contact", {}) or {}
        out: dict[str, int] = {}
        for dim, per_month in spec.items():
            if dim not in RELATIONSHIP_DIMENSIONS:
                continue
            amount = int(float(per_month) * months_elapsed)
            if amount <= 0:
                continue
            current = getattr(relationship, dim, 0)
            if current > 0:
                out[dim] = -min(amount, current)
            elif current < 0:
                out[dim] = min(amount, -current)
        return out

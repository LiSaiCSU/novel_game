"""ProposalValidator (Prompt section 18).

Everything an AI subsystem returns arrives here as a *proposal*. This module
converts the parts that survive validation into StateChange objects and
discards the rest with a recorded reason.

An AI can suggest that a character now hates the player. It cannot make it so,
and it cannot make it so by 60 points.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.characters.npc_agent import NPCDecisionResult
from engine.characters.schemas import DirectorDecision, NPCDecision
from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.models import Character, Emotion
from engine.core.mutations import ChangeSet, StateChange
from engine.core.ports import UnitOfWork
from engine.core.types import ActionType, ImportanceBand
from engine.relationships.manager import RelationshipManager, band_for_importance
from engine.world.state_view import WorldStateView


@dataclass(slots=True)
class ProposalReport:
    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    clamped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, list[str]]:
        return {"accepted": self.accepted, "rejected": self.rejected, "clamped": self.clamped}


class ProposalValidator:
    def __init__(self, pack: ContentPack, relationships: RelationshipManager) -> None:
        self.pack = pack
        self.relationships = relationships
        #: Personality is allowed to drift only this far per turn (Prompt section 13).
        self.personality_drift_cap = 0.02

    # ------------------------------------------------------------------
    async def apply_npc_decision(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        result: NPCDecisionResult,
        change_set: ChangeSet,
        *,
        importance: float,
        available_actions: list[str],
    ) -> ProposalReport:
        report = ProposalReport()
        npc = await uow.characters.get(result.npc_id)
        if npc is None or not npc.alive:
            report.rejected.append(f"npc_missing_or_dead:{result.npc_key}")
            return report

        decision = result.decision

        # -- the chosen action must be one the rules actually offered --------
        action_type = decision.decision.action_type
        if action_type and action_type not in available_actions:
            report.rejected.append(f"action_not_available:{result.npc_key}:{action_type}")
            decision.decision.action_type = str(ActionType.WAIT)
        else:
            report.accepted.append(f"action:{result.npc_key}:{action_type}")

        # -- named target must exist and be here -----------------------------
        if decision.decision.target:
            target = state.character_by_key(decision.decision.target)
            if target is None or not target.alive:
                report.rejected.append(f"target_invalid:{decision.decision.target}")
                decision.decision.target = None

        # -- emotion may move fast; personality may not ----------------------
        emotion_change = self._emotion_change(npc, decision, state.world.current_minute)
        if emotion_change is not None:
            change_set.add(emotion_change)
            report.accepted.append(f"emotion:{result.npc_key}")

        if decision.goal_update_proposal:
            goal_change = self._goal_change(npc, decision)
            if goal_change is not None:
                change_set.add(goal_change)
                report.accepted.append(f"goals:{result.npc_key}")

        # -- relationship deltas, clamped by the magnitude of what happened ---
        band = band_for_importance(importance)
        for who_key, deltas in decision.relationship_change_proposal.items():
            other = state.character_by_key(who_key)
            if other is None:
                report.rejected.append(f"relationship_target_unknown:{who_key}")
                continue
            clean, clamped_flags = self.relationships.clamp_deltas(deltas, band)
            if not clean:
                continue
            change_set.add(
                self.relationships.to_state_change(
                    npc.id, other.id, clean, reason=f"npc_decision:{result.npc_key}"
                )
            )
            report.accepted.append(f"relationship:{result.npc_key}->{who_key}:{clean}")
            for dim, was_clamped in clamped_flags.items():
                if was_clamped:
                    report.clamped.append(f"{result.npc_key}->{who_key}.{dim}")
        return report

    # ------------------------------------------------------------------
    def _emotion_change(
        self, npc: Character, decision: NPCDecision, minute: int
    ) -> StateChange | None:
        update = decision.emotion_update
        payload: dict[str, Any] = {}
        if update.dominant:
            payload["dominant"] = str(update.dominant)[:32]
        if update.valence is not None:
            payload["valence"] = max(-1.0, min(1.0, float(update.valence)))
        if update.arousal is not None:
            payload["arousal"] = max(0.0, min(1.0, float(update.arousal)))
        if update.intensity is not None:
            payload["intensity"] = max(0.0, min(1.0, float(update.intensity)))
        if not payload:
            return None
        payload["updated_at_minute"] = minute
        return mut.character_emotion(npc.id, payload, reason="npc_decision")

    def _goal_change(self, npc: Character, decision: NPCDecision) -> StateChange | None:
        proposal = decision.goal_update_proposal or {}
        payload: dict[str, object] = {}
        short = proposal.get("short_term_goals")
        if isinstance(short, list):
            payload["short_term_goals"] = [str(g)[:120] for g in short][:5]
        # A long-term goal is a character's spine. Changing it needs a major
        # cause, which a single turn's proposal is not, so it is ignored here.
        if not payload:
            return None
        return StateChange(
            kind=mut.ChangeKind.CHARACTER_GOALS,
            target_id=npc.id,
            payload=payload,
            reason="npc_goal_update",
        )

    # ------------------------------------------------------------------
    async def apply_director_decision(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        decision: DirectorDecision,
        change_set: ChangeSet,
        *,
        event_builder,
    ) -> ProposalReport:
        """Turn an accepted Director proposal into a world event and thread nudge."""
        from engine.core.types import DirectorDecisionType

        report = ProposalReport()
        if decision.decision is DirectorDecisionType.NO_EVENT:
            report.accepted.append("no_event")
            return report

        participants: list[Character] = []
        for key in decision.participants:
            character = await uow.characters.get_by_key(state.world.id, key)
            if character is not None and character.alive:
                participants.append(character)

        event = event_builder.build(
            decision.event_type or "FORESHADOWING",
            actor_id=participants[0].id if participants else None,
            target_ids=[c.id for c in participants[1:]],
            location_id=state.player.location_id,
            payload={
                "summary": decision.proposal,
                "narrative_purpose": decision.narrative_purpose,
                "source_plot_thread": decision.source_plot_thread,
                "urgency": str(decision.urgency),
            },
            causes=decision.causal_basis,
            world_minute=state.world.current_minute,
        )
        change_set.add_event(event)
        report.accepted.append(f"director_event:{event.event_type}")

        if decision.source_plot_thread:
            thread = await uow.plot_threads.get_by_key(
                state.world.id, decision.source_plot_thread
            )
            if thread is not None:
                payload = {
                    "last_advanced_minute": state.world.current_minute,
                    "stage": thread.stage
                    + (1 if decision.decision is DirectorDecisionType.ADVANCE_THREAD else 0),
                }
                change_set.add(
                    mut.plot_thread_update(thread.id, payload, reason="director_advance")
                )
                report.accepted.append(f"thread:{thread.key}")
        return report

    # ------------------------------------------------------------------
    def apply_tension(
        self, state: WorldStateView, change_set: ChangeSet, new_value: float
    ) -> None:
        before = state.world.narrative_tension
        if abs(new_value - before) < 0.05:
            return
        change_set.add(
            mut.world_tension(state.world.id, before, round(new_value, 2), reason="turn")
        )

    def band_for(self, importance: float) -> ImportanceBand:
        return band_for_importance(importance)


def emotion_from(payload: dict[str, Any], minute: int) -> Emotion:
    return Emotion(
        dominant=str(payload.get("dominant", "neutral")),
        valence=float(payload.get("valence", 0.0)),
        arousal=float(payload.get("arousal", 0.2)),
        intensity=float(payload.get("intensity", 0.3)),
        updated_at_minute=minute,
    )

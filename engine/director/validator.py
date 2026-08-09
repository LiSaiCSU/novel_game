"""Director proposal validation (Prompt sections 22, 24).

The Director suggests. This module decides whether the world can actually
accommodate the suggestion. Anything that fails is downgraded to NO_EVENT and
recorded, never silently patched up.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.characters.schemas import DirectorDecision
from engine.contentpack.pack import ContentPack
from engine.core.models import Character, PlotThread
from engine.core.ports import UnitOfWork
from engine.core.types import DirectorDecisionType, ThreadStatus
from engine.director.tension import TensionModel
from engine.world.state_view import WorldStateView


@dataclass(slots=True)
class ValidationOutcome:
    accepted: bool
    decision: DirectorDecision
    rejections: list[str] = field(default_factory=list)
    participants: list[Character] = field(default_factory=list)
    thread: PlotThread | None = None


class DirectorValidator:
    def __init__(self, pack: ContentPack) -> None:
        self.pack = pack
        self.tension = TensionModel(pack)
        self.allowed_event_types = set(pack.rule("director.allowed_event_types", []) or [])

    async def validate(
        self, uow: UnitOfWork, state: WorldStateView, decision: DirectorDecision
    ) -> ValidationOutcome:
        rejections: list[str] = []

        if decision.decision is DirectorDecisionType.NO_EVENT:
            return ValidationOutcome(accepted=True, decision=decision)

        # -- event type must be on the content pack's whitelist -------------
        if decision.event_type and decision.event_type not in self.allowed_event_types:
            rejections.append(f"event_type_not_allowed:{decision.event_type}")

        # -- participants must exist, be alive, and be able to get here ------
        participants: list[Character] = []
        for key in decision.participants:
            character = await uow.characters.get_by_key(state.world.id, key)
            if character is None:
                rejections.append(f"unknown_participant:{key}")
                continue
            if not character.alive:
                # Eval 5: the Director may not bring a dead character back.
                rejections.append(f"dead_participant:{key}")
                continue
            if not self._can_reach(state, character):
                rejections.append(f"unreachable_participant:{key}")
                continue
            participants.append(character)

        # -- thread must exist and still be open -----------------------------
        thread: PlotThread | None = None
        if decision.source_plot_thread:
            thread = await uow.plot_threads.get_by_key(state.world.id, decision.source_plot_thread)
            if thread is None:
                rejections.append(f"unknown_thread:{decision.source_plot_thread}")
            elif thread.status not in (ThreadStatus.ACTIVE, ThreadStatus.DORMANT):
                rejections.append(f"thread_closed:{thread.key}")
        elif decision.decision is DirectorDecisionType.ADVANCE_THREAD:
            rejections.append("advance_thread_without_thread")

        # -- causal basis must point at things that really happened ----------
        recent_ids = {e.id for e in await uow.events.list_recent(state.world.id, limit=60)}
        for basis in decision.causal_basis:
            if basis in recent_ids:
                continue
            if thread is not None and (
                basis in thread.foreshadowing
                or basis in thread.unresolved_questions
                or basis in thread.related_facts
                or basis == thread.next_beat_hint
            ):
                continue
            if await uow.knowledge.get_fact_by_key(state.world.id, basis) is not None:
                continue
            rejections.append(f"unfounded_causal_basis:{basis[:40]}")

        # -- pacing: no permanent climax --------------------------------------
        if self.tension.must_de_escalate(
            state.world.tension_history, state.world.narrative_tension
        ) and decision.tension_delta > 0:
            rejections.append("tension_already_saturated")

        if rejections:
            return ValidationOutcome(
                accepted=False,
                decision=DirectorDecision(decision=DirectorDecisionType.NO_EVENT),
                rejections=rejections,
            )
        return ValidationOutcome(
            accepted=True, decision=decision, participants=participants, thread=thread
        )

    # ------------------------------------------------------------------
    def _can_reach(self, state: WorldStateView, character: Character) -> bool:
        """A character with no location, or one with no route here, cannot appear."""
        here = state.location_key()
        if not here:
            return False
        if not character.location_key:
            return False
        if character.location_key == here:
            return True
        return state.graph.path(character.location_key, here) is not None

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
from engine.director.lifecycle import director_event_dedup_key
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
        self.max_schedule_delay = int(
            pack.rule("director.max_schedule_delay_minutes", 518_400)
        )
        self.max_events_per_day = max(
            1, int(pack.rule("director.max_events_per_day", 2))
        )

    async def validate(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        decision: DirectorDecision,
        *,
        unavailable_character_ids: set[str] | None = None,
    ) -> ValidationOutcome:
        rejections: list[str] = []

        if decision.decision is DirectorDecisionType.NO_EVENT:
            return ValidationOutcome(accepted=True, decision=decision)

        # -- event type must be on the content pack's whitelist -------------
        if not decision.event_type:
            rejections.append("missing_event_type")
        elif decision.event_type not in self.allowed_event_types:
            rejections.append(f"event_type_not_allowed:{decision.event_type}")
        if decision.schedule_after_minutes > self.max_schedule_delay:
            rejections.append(
                f"schedule_delay_too_large:{decision.schedule_after_minutes}"
            )

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
            if character.id in (unavailable_character_ids or set()):
                rejections.append(f"participant_dies_this_turn:{key}")
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
        open_threads = {
            row.key: row
            for row in await uow.plot_threads.list_for_world(state.world.id)
            if row.status in (ThreadStatus.ACTIVE, ThreadStatus.DORMANT)
        }
        for basis in decision.causal_basis:
            if basis in recent_ids:
                continue
            # An unresolved storyline is a cause in its own right, and it is
            # the only one available on turn one: a world that has not yet
            # produced an important event cannot cite an important event, so
            # the director's first proposal was rejected every single time.
            cited = open_threads.get(basis)
            if cited is not None:
                continue
            for candidate in (thread, *open_threads.values()):
                if candidate is not None and (
                    basis in candidate.foreshadowing
                    or basis in candidate.unresolved_questions
                    or basis in candidate.related_facts
                    or basis == candidate.next_beat_hint
                ):
                    cited = candidate
                    break
            if cited is not None:
                continue
            if await uow.knowledge.get_fact_by_key(state.world.id, basis) is not None:
                continue
            rejections.append(f"unfounded_causal_basis:{basis[:40]}")

        if not rejections:
            scheduled = state.world.current_minute + decision.schedule_after_minutes
            minutes_per_day = state.clock.minutes_per_day
            day_start = (scheduled // minutes_per_day) * minutes_per_day
            booked = await uow.director_events.count_booked_between(
                state.world.id, day_start, day_start + minutes_per_day
            )
            if booked >= self.max_events_per_day:
                rejections.append(f"director_daily_cap_reached:{day_start}")

        if not rejections:
            dedup_key = director_event_dedup_key(decision, thread)
            duplicate = await uow.director_events.get_by_dedup_key(
                state.world.id, dedup_key
            )
            if duplicate is not None:
                rejections.append(
                    f"duplicate_director_event:{duplicate.id}:{duplicate.status}"
                )

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

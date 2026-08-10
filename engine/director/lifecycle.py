"""Canonical lifecycle and deduplication for Director events."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from engine.characters.schemas import DirectorDecision
from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.models import (
    Character,
    DirectorEvent,
    DirectorEventTransition,
    PlotThread,
)
from engine.core.mutations import ChangeSet
from engine.core.ports import UnitOfWork
from engine.core.types import (
    DirectorDecisionType,
    DirectorEventStatus,
    ThreadStatus,
)
from engine.events.builder import EventBuilder
from engine.world.state_view import WorldStateView


def director_event_dedup_key(
    decision: DirectorDecision, thread: PlotThread | None
) -> str:
    """Stable identity of one causal beat, excluding mutable prose wording."""
    material = {
        "thread": thread.key if thread else None,
        "thread_stage": thread.stage if thread else None,
        "decision": str(decision.decision),
        "event_type": decision.event_type,
        "participants": sorted(set(decision.participants)),
        "causal_basis": sorted(set(decision.causal_basis)),
    }
    encoded = json.dumps(material, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(encoded.encode("utf-8"), digest_size=20).hexdigest()


@dataclass(slots=True)
class DueDirectorEventsReport:
    resolved: int = 0
    cancelled: int = 0
    tension_delta: float = 0.0
    rescheduled: int = 0


class DirectorEventLifecycleService:
    def __init__(self, pack: ContentPack) -> None:
        self.pack = pack
        self.max_events_per_day = max(
            1, int(pack.rule("director.max_events_per_day", 2))
        )
        self.minutes_per_day = int(pack.calendar.get("minutes_per_hour", 60)) * int(
            pack.calendar.get("hours_per_day", 24)
        )

    def propose(
        self,
        state: WorldStateView,
        decision: DirectorDecision,
        participants: list[Character],
        thread: PlotThread | None,
        *,
        session_id: str,
        turn_id: str,
        turn_number: int,
    ) -> DirectorEvent:
        now = state.world.current_minute
        scheduled = now + decision.schedule_after_minutes
        record = DirectorEvent(
            world_id=state.world.id,
            session_id=session_id,
            created_turn_id=turn_id,
            created_turn_number=turn_number,
            dedup_key=director_event_dedup_key(decision, thread),
            decision_type=decision.decision,
            event_type=decision.event_type or "FORESHADOWING",
            source_plot_thread_id=thread.id if thread else None,
            source_plot_thread_key=thread.key if thread else None,
            source_plot_thread_stage=thread.stage if thread else None,
            participant_keys=[character.key for character in participants],
            participant_ids=[character.id for character in participants],
            location_id=state.player.location_id,
            proposal=decision.proposal,
            causal_basis=list(decision.causal_basis),
            narrative_purpose=list(decision.narrative_purpose),
            urgency=decision.urgency,
            tension_delta=decision.tension_delta,
            proposed_at_minute=now,
            scheduled_for_minute=scheduled,
            history=[
                DirectorEventTransition(
                    status=DirectorEventStatus.PROPOSED,
                    at_minute=now,
                    reason="validated_proposal",
                )
            ],
        )
        return self._transition(
            record,
            DirectorEventStatus.SCHEDULED,
            now,
            "scheduled_immediately" if scheduled == now else "scheduled_for_future",
        )

    async def activate(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        record: DirectorEvent,
        change_set: ChangeSet,
        *,
        event_builder: EventBuilder,
        pending_deaths: dict[str, int] | None = None,
        thread_override: PlotThread | None = None,
    ) -> DirectorEventStatus:
        """Revalidate a due record, then materialize or cancel it atomically."""
        at_minute = record.scheduled_for_minute
        invalid_reason = await self._invalid_reason(
            uow,
            state,
            record,
            at_minute,
            pending_deaths or {},
            thread_override,
        )
        if invalid_reason:
            cancelled = self._transition(
                record,
                DirectorEventStatus.CANCELLED,
                at_minute,
                invalid_reason,
            )
            cancelled.cancelled_at_minute = at_minute
            cancelled.cancellation_reason = invalid_reason
            change_set.director_events.append(cancelled)
            return DirectorEventStatus.CANCELLED

        active = self._transition(
            record, DirectorEventStatus.ACTIVE, at_minute, "activation_validated"
        )
        active.activated_at_minute = at_minute
        cause_event_ids: list[str] = []
        textual_causes: list[str] = []
        for basis in active.causal_basis:
            if await uow.events.get(basis) is not None:
                cause_event_ids.append(basis)
            else:
                textual_causes.append(basis)
        event = event_builder.build(
            active.event_type,
            actor_id=active.participant_ids[0] if active.participant_ids else None,
            target_ids=active.participant_ids[1:],
            location_id=active.location_id,
            payload={
                "summary": active.proposal,
                "director_event_id": active.id,
                "source_plot_thread": active.source_plot_thread_key,
                "narrative_purpose": active.narrative_purpose,
                "urgency": str(active.urgency),
            },
            causes=textual_causes,
            cause_event_ids=cause_event_ids,
            world_minute=at_minute,
        )
        resolved = self._transition(
            active, DirectorEventStatus.RESOLVED, at_minute, "canonical_event_committed"
        )
        resolved.resolved_at_minute = at_minute
        resolved.canonical_event_id = event.id
        change_set.add_event(event)
        change_set.director_events.append(resolved)
        await self._advance_thread(
            uow, resolved, change_set, at_minute, thread_override=thread_override
        )
        return DirectorEventStatus.RESOLVED

    async def process_due(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        through_minute: int,
        change_set: ChangeSet,
        *,
        event_builder: EventBuilder,
    ) -> DueDirectorEventsReport:
        report = DueDirectorEventsReport()
        pending_deaths = {
            event.actor_id: event.world_minute
            for event in change_set.events
            if event.event_type == "DEATH" and event.actor_id
        }
        projected_threads: dict[str, PlotThread] = {}
        resolved_by_day: dict[int, int] = {}
        for record in await uow.director_events.list_due(state.world.id, through_minute):
            day_start = (
                record.scheduled_for_minute // self.minutes_per_day
            ) * self.minutes_per_day
            while True:
                if day_start not in resolved_by_day:
                    resolved_by_day[day_start] = (
                        await uow.director_events.count_resolved_between(
                            state.world.id,
                            day_start,
                            day_start + self.minutes_per_day,
                        )
                    )
                if resolved_by_day[day_start] < self.max_events_per_day:
                    break
                old_scheduled = record.scheduled_for_minute
                record = self._transition(
                    record,
                    DirectorEventStatus.SCHEDULED,
                    old_scheduled,
                    "daily_event_cap_reschedule",
                )
                record.scheduled_for_minute += self.minutes_per_day
                day_start += self.minutes_per_day
                report.rescheduled += 1
            if record.scheduled_for_minute > through_minute:
                change_set.director_events.append(record)
                continue
            thread_override = None
            if record.source_plot_thread_key:
                thread_override = projected_threads.get(record.source_plot_thread_key)
                if thread_override is None:
                    stored_thread = await uow.plot_threads.get_by_key(
                        record.world_id, record.source_plot_thread_key
                    )
                    if stored_thread is not None:
                        thread_override = stored_thread.model_copy(deep=True)
                        projected_threads[record.source_plot_thread_key] = thread_override
            status = await self.activate(
                uow,
                state,
                record,
                change_set,
                event_builder=event_builder,
                pending_deaths=pending_deaths,
                thread_override=thread_override,
            )
            if status is DirectorEventStatus.RESOLVED:
                report.resolved += 1
                report.tension_delta += record.tension_delta
                resolved_by_day[day_start] += 1
                if thread_override is not None:
                    thread_override.last_advanced_minute = record.scheduled_for_minute
                    if record.decision_type is DirectorDecisionType.ADVANCE_THREAD:
                        thread_override.stage += 1
            else:
                report.cancelled += 1
        return report

    async def _invalid_reason(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        record: DirectorEvent,
        at_minute: int,
        pending_deaths: dict[str, int],
        thread_override: PlotThread | None,
    ) -> str:
        for character_id in record.participant_ids:
            character = await uow.characters.get(character_id)
            if character is None:
                return f"participant_missing:{character_id}"
            death_minute = pending_deaths.get(character_id)
            if not character.alive or (
                death_minute is not None and death_minute <= at_minute
            ):
                return f"participant_dead:{character_id}"
            if record.location_id:
                destination = state.graph.by_id(record.location_id)
                if (
                    destination is None
                    or not character.location_key
                    or state.graph.path(character.location_key, destination.key) is None
                ):
                    return f"participant_unreachable:{character_id}"
        if record.source_plot_thread_key:
            thread = thread_override or await uow.plot_threads.get_by_key(
                record.world_id, record.source_plot_thread_key
            )
            if thread is None:
                return "source_thread_missing"
            if thread.status not in (ThreadStatus.ACTIVE, ThreadStatus.DORMANT):
                return f"source_thread_closed:{thread.status}"
            if thread.stage != record.source_plot_thread_stage:
                return "source_thread_stage_changed"
        return ""

    async def _advance_thread(
        self,
        uow: UnitOfWork,
        record: DirectorEvent,
        change_set: ChangeSet,
        at_minute: int,
        *,
        thread_override: PlotThread | None = None,
    ) -> None:
        if not record.source_plot_thread_key:
            return
        thread = thread_override or await uow.plot_threads.get_by_key(
            record.world_id, record.source_plot_thread_key
        )
        if thread is None:
            return
        stage = thread.stage + (
            1 if record.decision_type is DirectorDecisionType.ADVANCE_THREAD else 0
        )
        change_set.add(
            mut.plot_thread_update(
                thread.id,
                {"last_advanced_minute": at_minute, "stage": stage},
                reason="director_event_resolved",
            )
        )

    def _transition(
        self,
        record: DirectorEvent,
        status: DirectorEventStatus,
        at_minute: int,
        reason: str,
    ) -> DirectorEvent:
        updated = record.model_copy(deep=True)
        updated.status = status
        updated.history.append(
            DirectorEventTransition(status=status, at_minute=at_minute, reason=reason)
        )
        return updated

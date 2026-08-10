"""AI Director (Prompt sections 22-25).

The Director does not manage the world; it decides which of the consequences
the world already owes should surface now. Its default answer is NO_EVENT, and
its deterministic fallback keeps that discipline without a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.characters.schemas import DirectorDecision
from engine.contentpack.pack import ContentPack
from engine.context.builder import ContextBuilder
from engine.core.errors import LLMError, StructuredOutputError
from engine.core.logging import get_logger
from engine.core.models import PlotThread
from engine.core.ports import UnitOfWork
from engine.core.types import DirectorDecisionType, LLMRole, ThreadStatus, Urgency
from engine.director.tension import TensionModel
from engine.director.validator import DirectorValidator, ValidationOutcome
from engine.world.state_view import WorldStateView

logger = get_logger("director")


@dataclass(slots=True)
class DirectorResult:
    decision: DirectorDecision
    validation: ValidationOutcome
    consulted: bool
    degraded: bool
    skip_reason: str = ""
    debug: dict[str, object] = field(default_factory=dict)


class Director:
    def __init__(
        self,
        pack: ContentPack,
        context_builder: ContextBuilder,
        llm=None,
        registry=None,
        prompt_version: str = "v1",
        min_interval_turns: int | None = None,
    ) -> None:
        self.pack = pack
        self.context_builder = context_builder
        self.llm = llm
        self.registry = registry
        self.prompt_version = prompt_version
        self.tension = TensionModel(pack)
        self.validator = DirectorValidator(pack)
        self.min_interval = (
            int(pack.rule("director.min_interval_turns", 3))
            if min_interval_turns is None
            else min_interval_turns
        )
        self.high_importance_override = float(
            pack.rule("director.high_importance_override", 0.7)
        )

    # ------------------------------------------------------------------
    def should_consult(
        self, *, turns_since_last_event: int, last_turn_importance: float, overdue_threads: int
    ) -> tuple[bool, str]:
        """Cost control and pacing in one place (Prompt section 6)."""
        if last_turn_importance >= self.high_importance_override:
            return True, "high_importance_turn"
        if overdue_threads > 0:
            return True, "overdue_thread"
        if turns_since_last_event >= self.min_interval:
            return True, "interval_reached"
        return False, f"cooldown({turns_since_last_event}/{self.min_interval})"

    # ------------------------------------------------------------------
    async def direct(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        *,
        turns_since_last_event: int,
        last_turn_importance: float,
        rng,
        unavailable_character_ids: set[str] | None = None,
    ) -> DirectorResult:
        threads = await uow.plot_threads.list_for_world(state.world.id)
        overdue = self._overdue(threads, state.world.current_minute)

        consult, reason = self.should_consult(
            turns_since_last_event=turns_since_last_event,
            last_turn_importance=last_turn_importance,
            overdue_threads=len(overdue),
        )
        no_event = DirectorDecision(decision=DirectorDecisionType.NO_EVENT)
        if not consult:
            return DirectorResult(
                decision=no_event,
                validation=ValidationOutcome(accepted=True, decision=no_event),
                consulted=False,
                degraded=False,
                skip_reason=reason,
            )

        decision: DirectorDecision | None = None
        degraded = True
        if self.llm is not None and self.registry is not None and self.llm.usable_for(
            LLMRole.DIRECTOR
        ):
            try:
                context = await self.context_builder.build_director_context(
                    uow, state, turns_since_last_event=turns_since_last_event
                )
                prompt = self.registry.render(
                    "director",
                    self.prompt_version,
                    schema=self.llm.schema_hint(DirectorDecision),
                    **context.sections,
                )
                decision = await self.llm.generate_structured(
                    LLMRole.DIRECTOR,
                    DirectorDecision,
                    prompt,
                    prompt_version=self.prompt_version,
                )
                degraded = False
            except (LLMError, StructuredOutputError) as exc:
                logger.warning("director fell back to deterministic scheduling: %s", exc)
                self.llm.record_degraded(LLMRole.DIRECTOR, str(exc))

        if decision is None:
            decision = self._deterministic(state, threads, overdue, rng)

        validation = await self.validator.validate(
            uow,
            state,
            decision,
            unavailable_character_ids=unavailable_character_ids,
        )
        if not validation.accepted:
            logger.info("director proposal rejected: %s", validation.rejections)
        return DirectorResult(
            decision=validation.decision,
            validation=validation,
            consulted=True,
            degraded=degraded,
            skip_reason="",
            debug={
                "reason": reason,
                "overdue_threads": [t.key for t in overdue],
                "tension": self.tension.describe(
                    state.world.narrative_tension, state.world.tension_history
                ),
            },
        )

    # ------------------------------------------------------------------
    def _overdue(self, threads: list[PlotThread], now_minute: int) -> list[PlotThread]:
        """Threads the world has left hanging longer than their own pressure allows."""
        out: list[PlotThread] = []
        for thread in threads:
            if thread.status is not ThreadStatus.ACTIVE:
                continue
            if thread.escalation_pressure <= 0:
                continue
            # higher pressure -> shorter patience
            patience_minutes = int(10_080 / max(0.05, thread.escalation_pressure))
            if now_minute - thread.last_advanced_minute >= patience_minutes:
                out.append(thread)
        out.sort(key=lambda t: t.importance, reverse=True)
        return out

    def _deterministic(
        self,
        state: WorldStateView,
        threads: list[PlotThread],
        overdue: list[PlotThread],
        rng,
    ) -> DirectorDecision:
        """No model, no chaos: advance the most overdue thread, or stay quiet.

        Note it never invents a new thread. Prompt section 23: develop what
        already exists rather than manufacturing novelty.
        """
        if self.tension.must_de_escalate(
            state.world.tension_history, state.world.narrative_tension
        ):
            return DirectorDecision(
                decision=DirectorDecisionType.NO_EVENT, proposal="tension needs to fall"
            )
        if not overdue:
            return DirectorDecision(decision=DirectorDecisionType.NO_EVENT)

        thread = overdue[0]
        reachable = [
            key
            for key in thread.participants
            if key != state.player.key
        ]
        if not reachable:
            return DirectorDecision(decision=DirectorDecisionType.NO_EVENT)

        # A quiet beat: plant foreshadowing rather than stage a confrontation.
        basis = [b for b in (thread.foreshadowing + thread.related_facts) if b][:2]
        return DirectorDecision(
            decision=DirectorDecisionType.PLANT_FORESHADOWING,
            source_plot_thread=thread.key,
            event_type="FORESHADOWING",
            participants=reachable[:1],
            proposal=thread.next_beat_hint or thread.name,
            causal_basis=basis,
            narrative_purpose=[f"advance:{thread.key}"],
            urgency=Urgency.LOW,
            tension_delta=min(6.0, thread.importance * 8.0),
        )

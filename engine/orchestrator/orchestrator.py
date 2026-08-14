"""GameOrchestrator - the turn scheduler (Prompt section 6).

It writes no prose and decides no outcomes. It sequences the subsystems, holds
the transaction boundary, enforces idempotency, budgets AI calls, and records
what happened.

Stage order (see docs/GAME_LOOP.md):
    ingest, snapshot, intent, plan, validate, resolve, npc, simulate, direct,
    validate2, guard, commit, memory, narrate, respond
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

from engine.actions.autopilot import Autopilot
from engine.actions.intent_parser import IntentParser, ParsedIntent
from engine.actions.planner import ActionPlanExecutor
from engine.actions.resolver import ActionResolver
from engine.actions.schema import Action, ActionOutcome, PlayerIntent, RuleResult
from engine.characters.npc_agent import NPCAgent
from engine.contentpack.declarative_runtime import apply_declarative_rules
from engine.contentpack.pack import ContentPack
from engine.context.builder import ContextBuilder
from engine.core import mutations as mut
from engine.core.errors import ConsistencyViolation, EngineError
from engine.core.locks import IdempotencyStore, LockBackend
from engine.core.logging import bind, get_logger
from engine.core.models import Character, GameSession, NarrativeSegment
from engine.core.mutations import ChangeSet
from engine.core.ports import UnitOfWork
from engine.core.types import QUERY_ACTIONS, ActionType, CharacterType, Visibility
from engine.director.director import Director
from engine.director.tension import TensionModel
from engine.events.builder import EventBuilder
from engine.knowledge.service import KnowledgeService
from engine.memory.extractor import MemoryExtractor
from engine.narrative.chapter import (
    ChapterRenderer,
    ChapterResult,
    ChapterStep,
    ChunkListener,
)
from engine.narrative.prologue import Prologue, PrologueResult
from engine.narrative.renderer import NarrativeRenderer, NarrativeResult
from engine.orchestrator.canonical import commit_canonical_turn, recovery_capsule
from engine.orchestrator.interrupt import Interrupt, InterruptDetector, InterruptReason
from engine.orchestrator.npc_phase import NpcPhase
from engine.orchestrator.proposals import ProposalValidator
from engine.orchestrator.turn import (
    DEFAULT_NARRATIVE_CHARS,
    Choice,
    OrchestratorPlan,
    StageTimer,
    StoryBeat,
    TurnRequest,
    TurnResult,
    TurnStatus,
    TurnTrace,
    record_llm_calls,
    record_rng,
    require_turn_transition,
)
from engine.relationships.manager import RelationshipManager, band_for_importance
from engine.rng.game_rng import GameRNG, event_rng
from engine.rules.base import RuleContext
from engine.rules.engine import RuleEngine
from engine.simulation.simulator import WorldSimulator
from engine.world.consistency import ConsistencyGuard
from engine.world.location_graph import LocationGraph
from engine.world.state_view import WorldStateView, build_world_state
from engine.world.steward import StewardResult, WorldSteward

logger = get_logger("orchestrator")

#: Called as each step of a run commits, so a caller can show progress while
#: the rest of the chapter is still being played out.
StepListener = Callable[[int, "ChapterStep"], Awaitable[None]]

#: Narrative segment kind used to persist a chapter's unanswered question. It
#: is bookkeeping, not prose, so it never appears in `recent_narrative`.
BEAT_SEGMENT = "beat"


@dataclass(slots=True)
class AdvanceBudget:
    """How far the story may run before it checks back in regardless."""

    max_steps: int
    max_minutes: int


@dataclass(slots=True)
class StepOutcome:
    """One committed step of a run, plus whether it ended the run."""

    turn_id: str = ""
    step: ChapterStep | None = None
    interrupt: Interrupt | None = None
    degraded: bool = False
    #: Set only when nothing was committed because the input was unreadable.
    clarification: TurnResult | None = None

    def committed_step(self) -> ChapterStep:
        """The step, given that this outcome committed one."""
        if self.step is None:
            raise EngineError("advance step committed nothing", turn_id=self.turn_id)
        return self.step


@dataclass(slots=True)
class OrchestratorDeps:
    pack: ContentPack
    rules: RuleEngine
    intent_parser: IntentParser
    context_builder: ContextBuilder
    knowledge: KnowledgeService
    npc_agent: NPCAgent
    director: Director
    simulator: WorldSimulator
    narrative: NarrativeRenderer
    memory: MemoryExtractor
    relationships: RelationshipManager
    guard: ConsistencyGuard
    chapter: ChapterRenderer
    interrupts: InterruptDetector
    steward: WorldSteward | None = None
    autopilot: Autopilot | None = None
    prologue: Prologue | None = None
    llm: Any | None = None
    locks: LockBackend | None = None
    idempotency: IdempotencyStore | None = None
    debug_mode: bool = True


class GameOrchestrator:
    def __init__(self, deps: OrchestratorDeps) -> None:
        self.d = deps
        self.tension = TensionModel(deps.pack)
        self.proposals = ProposalValidator(deps.pack, deps.relationships)
        self.npc_phase = NpcPhase(
            pack=deps.pack,
            rules=deps.rules,
            knowledge=deps.knowledge,
            agent=deps.npc_agent,
            proposals=self.proposals,
            narrative=deps.narrative,
        )

    # ==================================================================
    async def open_session(
        self,
        uow: UnitOfWork,
        session: GameSession,
        state: WorldStateView,
        *,
        max_chars: int = DEFAULT_NARRATIVE_CHARS,
    ) -> PrologueResult:
        """Write the first chapter and give the character something to want.

        The goals land on the character record through the normal change set,
        so from here on the autopilot and the director can both read them.
        """
        if self.d.prologue is None:
            return PrologueResult(text="", degraded=True)
        if max_chars == DEFAULT_NARRATIVE_CHARS:
            # Keep the long-standing two-argument seam convenient for tests
            # and third-party prologue implementations.
            result = await self.d.prologue.write(uow, state)
        else:
            result = await self.d.prologue.write(uow, state, max_chars=max_chars)

        # The opening chapter has to be *recorded*, not just returned. The
        # player's first move is an answer to it, and until this was written
        # down the engine had never seen the text it was answering - so a line
        # like "go see what that notice says" resolved against nothing and the
        # story wandered off to whatever the character's goals suggested.
        if result.text:
            await uow.turns.append_narrative(
                NarrativeSegment(
                    session_id=session.id,
                    kind="chapter",
                    text=result.text,
                    world_minute=state.world.current_minute,
                )
            )
        if result.beat is not None:
            await uow.turns.append_narrative(
                NarrativeSegment(
                    session_id=session.id,
                    kind=BEAT_SEGMENT,
                    text=result.beat.model_dump_json(),
                    world_minute=state.world.current_minute,
                )
            )
        if result.text or result.beat is not None:
            await uow.commit()
        if result.goals:
            change_set = ChangeSet()
            change_set.add(
                mut.character_field(
                    state.player.id,
                    "short_term_goals",
                    list(state.player.short_term_goals),
                    result.goals,
                    reason="prologue",
                )
            )
            await uow.apply(change_set)
            await uow.commit()
        return result

    async def advance(
        self,
        uow: UnitOfWork,
        request: TurnRequest,
        on_step: StepListener | None = None,
        on_chunk: ChunkListener | None = None,
    ) -> TurnResult:
        """Play one explicit action, or continue autonomously when asked.

        A compound request is already compiled into one atomic action plan.
        Autopilot is reserved for the explicit content-pack "continue" command;
        otherwise it can turn a harmless observation into several choices the
        player never made. A delegated run stops at the first interruption and
        is written as one chapter.

        Every step is still an ordinary, fully adjudicated, individually
        committed turn. What changed is who decides to take it and when the
        prose gets written.

        ``on_step`` is notified as each step commits. A run covers several
        turns, so without it the caller has nothing to show for the better
        part of a minute - and a quiet minute is indistinguishable from a
        hang.
        """
        session = await uow.sessions.get(request.session_id)
        if session is None:
            raise EngineError("session not found", session_id=request.session_id)

        lock = self.d.locks
        if lock is None:
            return await self._advance(uow, request, session, on_step, on_chunk)
        async with lock.acquire(f"world:{session.world_id}"):
            return await self._advance(uow, request, session, on_step, on_chunk)

    async def _advance(
        self,
        uow: UnitOfWork,
        request: TurnRequest,
        session: GameSession,
        on_step: StepListener | None = None,
        on_chunk: ChunkListener | None = None,
    ) -> TurnResult:
        d = self.d
        timer = StageTimer()
        request_id = request.request_id or str(uuid.uuid4())

        # A retried request must never make the character act twice.
        if request.idempotency_key:
            existing = await uow.turns.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                self._require_same_idempotent_request(request, existing)
                stored_result = existing.get("result") or {}
                if stored_result:
                    logger.info("replaying completed run for idempotency key")
                    return TurnResult(**stored_result)
                # Canonical state already exists.  Even if a prior process
                # died before closing the whole chapter, the safe recovery is
                # presentation-only; never execute the player's action again.
                return await self._resume_or_replay(uow, request, session, existing)

        budget = self._advance_budget()
        steps: list[ChapterStep] = []
        turn_ids: list[str] = []
        interrupt: Interrupt | None = None
        arc = ""
        minutes_spent = 0
        degraded = False
        run_llm_records: list[Any] = []

        delegated = self._is_continue(request.text)
        player_led = bool(request.text.strip()) and not delegated

        # -- the player's own move, if they made one -------------------------
        if player_led:
            outcome = await self._advance_step(
                uow,
                request,
                session,
                request_id,
                timer,
                text=request.text,
                idempotency_key=request.idempotency_key,
            )
            if outcome.clarification is not None:
                return outcome.clarification
            step = outcome.committed_step()
            steps.append(step)
            turn_ids.append(outcome.turn_id)
            minutes_spent += step.minutes
            interrupt = outcome.interrupt
            degraded = degraded or outcome.degraded
            await self._notify(on_step, len(steps), step)
            if d.llm is not None:
                run_llm_records.extend(d.llm.records)

        # -- then the character carries on by themselves ---------------------
        # Only with a model behind it. The deterministic fallback picks the
        # same safe action every time, so running it five times would just
        # make the character meditate five times - worse than not running.
        if interrupt is None and delegated and d.autopilot is not None and d.autopilot.usable():
            state = await build_world_state(
                uow, d.pack, session.world_id, session.player_character_id
            )
            remaining = budget.max_steps - len(steps)
            if remaining > 0:
                before_autopilot = len(d.llm.records) if d.llm is not None else 0
                with timer.measure("autopilot"):
                    # The run continues what the player asked for. Without
                    # these two the planner falls back on standing goals and
                    # quietly takes the story somewhere else.
                    intents, arc = await d.autopilot.plan_run(
                        state,
                        steps=remaining,
                        recent_narrative=await self._recent_narrative(uow, session.id),
                        player_input=request.text if player_led else "",
                        player_did=steps[0].action if steps else "",
                    )
                if d.llm is not None:
                    run_llm_records.extend(d.llm.records[before_autopilot:])
                for intent in intents:
                    if minutes_spent >= budget.max_minutes:
                        break
                    outcome = await self._advance_step(
                        uow,
                        request,
                        session,
                        request_id,
                        timer,
                        forced_intent=intent,
                        # Only the run as a whole answers to the request's key.
                        idempotency_key=(request.idempotency_key if not turn_ids else None),
                    )
                    if outcome.clarification is not None:
                        break
                    step = outcome.committed_step()
                    steps.append(step)
                    turn_ids.append(outcome.turn_id)
                    minutes_spent += step.minutes
                    degraded = degraded or outcome.degraded
                    await self._notify(on_step, len(steps), step)
                    if d.llm is not None:
                        run_llm_records.extend(d.llm.records)
                    if outcome.interrupt is not None:
                        interrupt = outcome.interrupt
                        break

        if not steps:
            # Nothing was committed at all - treat it as an idle beat rather
            # than an error, exactly like unreadable input.
            state = await build_world_state(
                uow, d.pack, session.world_id, session.player_character_id
            )
            return await self._idle_turn(uow, session, state, request, request_id)

        if interrupt is None:
            interrupt = Interrupt(InterruptReason.BUDGET, "run_complete")

        # -- one chapter for the whole run -----------------------------------
        state = await build_world_state(uow, d.pack, session.world_id, session.player_character_id)
        before_chapter = len(d.llm.records) if d.llm is not None else 0
        with timer.measure("chapter"):
            chapter = await d.chapter.render(
                uow,
                state,
                steps,
                interrupt=interrupt,
                recent_narrative=await self._recent_narrative(uow, session.id),
                arc=arc,
                on_chunk=on_chunk,
                max_chars=request.narrative_max_chars,
            )
        if d.llm is not None:
            run_llm_records.extend(d.llm.records[before_chapter:])
            # Usage accounting runs after advance() returns. Preserve the
            # whole run rather than only the final step plus chapter.
            d.llm.records = run_llm_records
        return await self._close_run(
            uow,
            session,
            request,
            state,
            turn_ids=turn_ids,
            chapter=chapter,
            interrupt=interrupt,
            timer=timer,
            degraded=degraded or chapter.degraded,
            llm_calls=record_llm_calls(run_llm_records),
        )

    async def play_turn(self, uow: UnitOfWork, request: TurnRequest) -> TurnResult:
        timer = StageTimer()
        turn_id = str(uuid.uuid4())
        request_id = request.request_id or str(uuid.uuid4())

        # -- S0 ingest -----------------------------------------------------
        with timer.measure("ingest"):
            session = await uow.sessions.get(request.session_id)
            if session is None:
                raise EngineError("session not found", session_id=request.session_id)
            bind(
                request_id=request_id,
                turn_id=turn_id,
                world_id=session.world_id,
                session_id=session.id,
            )
            if request.idempotency_key:
                existing = await uow.turns.get_by_idempotency_key(request.idempotency_key)
                if existing is not None:
                    return await self._resume_or_replay(uow, request, session, existing)

        lock = self.d.locks
        if lock is None:
            return await self._run(uow, request, session, turn_id, request_id, timer)
        async with lock.acquire(f"world:{session.world_id}"):
            # The pre-lock lookup is only a fast path.  This second lookup is
            # the concurrency boundary that prevents two requests with the
            # same key from both adjudicating the action.
            if request.idempotency_key:
                existing = await uow.turns.get_by_idempotency_key(request.idempotency_key)
                if existing is not None:
                    return await self._resume_or_replay(uow, request, session, existing)
            return await self._run(uow, request, session, turn_id, request_id, timer)

    # ==================================================================
    async def _run(
        self,
        uow: UnitOfWork,
        request: TurnRequest,
        session: GameSession,
        turn_id: str,
        request_id: str,
        timer: StageTimer,
        *,
        narrate: bool = True,
        forced_intent: PlayerIntent | None = None,
    ) -> TurnResult:
        """Adjudicate and commit one turn.

        ``narrate=False`` stops after the canonical commit and hands back a
        result still marked ``CANONICAL_COMMITTED``. That is the documented
        resumable state, and it is what lets a run of several steps be written
        up as a single chapter instead of one paragraph per step.
        """
        d = self.d
        trace = TurnTrace(
            turn_id=turn_id,
            request_id=request_id,
            session_id=session.id,
            world_id=session.world_id,
        )
        if d.llm is not None:
            d.llm.reset_records()

        # -- S1 snapshot ----------------------------------------------------
        with timer.measure("snapshot"):
            state = await build_world_state(
                uow, d.pack, session.world_id, session.player_character_id
            )
            turn_number = session.turn_number + 1
            rng = event_rng(state.world.world_seed, session.session_seed, f"turn-{turn_number}")
            ctx = RuleContext(pack=d.pack, state=state, rng=rng)
            recent_narrative = await self._recent_narrative(uow, session.id)
            # Snapshot primitives, not object references: after commit the
            # repository may hand back the very objects this view was built
            # from, and a before/after diff of one object is always empty.
            before_facts = self._capture(state)

        # -- S2 intent ------------------------------------------------------
        with timer.measure("intent"):
            world_characters = await uow.characters.list_for_world(session.world_id)
            autopilot_reason = ""
            if forced_intent is not None:
                # A step the character chose for themselves during a run. It is
                # bound and adjudicated exactly like anything the player types.
                action_, plan_, notes_ = d.intent_parser.resolve(state, forced_intent)
                parsed = ParsedIntent(
                    intent=forced_intent,
                    action=action_,
                    plan=plan_,
                    degraded=False,
                    resolution_notes=notes_,
                )
                autopilot_reason = str(forced_intent.goal.details or "")
            elif self._is_continue(request.text) and d.autopilot is not None:
                # The player asked the story to keep going. Their character
                # still acts - through the same rules as any typed action.
                parsed, autopilot_reason = await self._autopilot_intent(
                    d.autopilot, state, recent_narrative
                )
            else:
                parsed = await d.intent_parser.parse(
                    uow,
                    state,
                    request.text,
                    recent_narrative=recent_narrative,
                    world_characters=world_characters,
                    pending_beat=await self._pending_beat(uow, session.id),
                )
            trace.intent = {
                **parsed.intent.model_dump(mode="json"),
                "compiled_plan": parsed.plan.model_dump(mode="json"),
                "degraded": parsed.degraded,
                "resolution_notes": parsed.resolution_notes,
            }

        # Truly unreadable input (empty, gibberish) is the only dead end left,
        # and it still costs the player nothing.
        if parsed.intent.needs_clarification():
            return await self._clarification_turn(
                uow, session, state, turn_id, turn_number, parsed, trace, timer, request
            )

        # -- S2b steward: the world grows to meet the player ------------------
        steward_result: StewardResult | None = None
        steward_changes: list[mut.StateChange] = []
        if parsed.needs_steward and d.steward is not None:
            with timer.measure("steward"):
                steward_result = await self._run_steward(
                    d.steward, state, parsed, world_characters, recent_narrative
                )
                if steward_result.grew_the_world:
                    state = self._extend_state(state, steward_result)
                    ctx = RuleContext(pack=d.pack, state=state, rng=rng)
                    steward_changes = list(steward_result.changes)
                parsed = d.intent_parser.rebind(state, parsed, steward_result)
                trace.proposals["steward"] = steward_result.as_dict()
                trace.intent["after_steward"] = {
                    "action_type": str(parsed.action.action_type),
                    "target_id": parsed.action.target_id,
                    "target_location_id": parsed.action.target_location_id,
                    "resolution_notes": parsed.resolution_notes,
                }

        action = parsed.action

        # -- S3 plan --------------------------------------------------------
        with timer.measure("plan"):
            plan = self._plan(action, state)
            trace.stage_timings["plan"] = 0

        # -- S4 validate ----------------------------------------------------
        with timer.measure("validate"):
            is_multi_action = len(parsed.plan.primitives) > 1
            rule_result = (
                RuleResult.ok(action_plan=True)
                if is_multi_action
                else d.rules.validate_action(ctx, action)
            )
            trace.rule_result = rule_result.model_dump(mode="json")
            if not rule_result.allowed:
                plan = OrchestratorPlan.for_rejection()

        # -- S5 resolve -----------------------------------------------------
        with timer.measure("resolve"):
            event_builder = EventBuilder(d.pack, state.world.id, turn_id=turn_id)
            resolver = ActionResolver(event_builder, d.relationships)
            if is_multi_action:
                plan_result = ActionPlanExecutor(
                    d.rules,
                    resolver,
                    max_total_minutes=int(d.pack.rule("action_plan.max_total_minutes", 1440)),
                ).execute(ctx, parsed.plan)
                rule_result = plan_result.rule_result
                outcome = plan_result.outcome
                change_set = plan_result.change_set
                action = plan_result.representative_action
                trace.proposals["action_plan"] = {
                    "atomic": True,
                    "steps": plan_result.steps,
                }
                trace.rule_result = rule_result.model_dump(mode="json")
                if not rule_result.allowed:
                    plan = OrchestratorPlan.for_rejection()
            else:
                outcome, change_set = resolver.resolve(ctx, action, rule_result)
            # The world grew before the action resolved, so the new rows commit
            # with it - including when the action itself was refused, because
            # the shop the player walked into exists either way.
            change_set.changes[:0] = steward_changes
            trace.outcome = outcome.model_dump(mode="json")

        # -- S6 npc ---------------------------------------------------------
        # Decisions themselves land in the trace; only the spoken lines flow on
        # to the narrative stage.
        npc_lines: list[str] = []
        if plan.needs_npcs:
            with timer.measure("npc"):
                npc_lines = await self._run_npcs(uow, ctx, action, outcome, change_set, trace)

        # -- S7 simulate ----------------------------------------------------
        simulation_report = None
        if plan.needs_simulation and outcome.time_cost_minutes > 0:
            with timer.measure("simulate"):
                simulation_report = await d.simulator.advance(
                    uow,
                    state,
                    outcome.time_cost_minutes,
                    change_set,
                    rng=rng.derive("simulation"),
                    event_builder=event_builder,
                )
                trace.simulation = simulation_report.as_dict()

        # -- S8 direct ------------------------------------------------------
        director_result = None
        director_state = self._projected_state(state, change_set, outcome.time_cost_minutes)
        scheduled_director_resolved = bool(
            simulation_report is not None and simulation_report.director_events_resolved > 0
        )
        if plan.needs_director and not scheduled_director_resolved:
            with timer.measure("direct"):
                turns_since = await self._turns_since_director(uow, session)
                unavailable = {
                    change.target_id
                    for change in change_set.by_kind(mut.ChangeKind.CHARACTER_DEATH)
                }
                director_result = await d.director.direct(
                    uow,
                    director_state,
                    turns_since_last_event=turns_since,
                    last_turn_importance=outcome.importance,
                    rng=rng.derive("director"),
                    unavailable_character_ids=unavailable,
                )
                trace.director = {
                    "decision": director_result.decision.model_dump(mode="json"),
                    "consulted": director_result.consulted,
                    "degraded": director_result.degraded,
                    "skip_reason": director_result.skip_reason,
                    "rejections": director_result.validation.rejections,
                    "debug": director_result.debug,
                }
        elif scheduled_director_resolved:
            trace.director = {
                "decision": {"decision": "NO_EVENT"},
                "consulted": False,
                "degraded": False,
                "skip_reason": "scheduled_director_event_resolved",
                "rejections": [],
                "debug": {},
            }

        # -- S9 validate2: AI proposals become state, or do not ---------------
        with timer.measure("validate2"):
            if director_result is not None and director_result.validation.accepted:
                report = await self.proposals.apply_director_decision(
                    uow,
                    director_state,
                    director_result.decision,
                    change_set,
                    event_builder=event_builder,
                    session_id=session.id,
                    turn_id=turn_id,
                    turn_number=turn_number,
                )
                trace.proposals["director"] = report.as_dict()

            new_tension = self._new_tension(state, outcome, director_result, simulation_report)
            self.proposals.apply_tension(state, change_set, new_tension)

            if outcome.time_cost_minutes > 0:
                change_set.add(
                    mut.world_time(
                        state.world.id,
                        state.world.current_minute,
                        state.world.current_minute + outcome.time_cost_minutes,
                        reason="turn",
                    )
                )

            applied_rules = apply_declarative_rules(d.pack, state, action, outcome, change_set)
            if applied_rules:
                trace.proposals["declarative_rules"] = {"applied": applied_rules}

        # -- S10 guard ------------------------------------------------------
        with timer.measure("guard"):
            try:
                violations = d.guard.check(state, change_set)
                trace.consistency = violations
            except ConsistencyViolation as exc:
                trace.errors.append(exc.to_dict())
                await uow.rollback()
                logger.error("consistency violation, turn rolled back: %s", exc.message)
                raise

        # -- S11 commit -----------------------------------------------------
        with timer.measure("commit"):
            trace.state_changes = change_set.summary()
            trace.rng_traces = record_rng(rng.traces)
            self._refresh_llm_trace(trace)
            capsule = recovery_capsule(
                # On an autopilot turn the literal input is "继续", which
                # tells the narrator nothing. Hand it the move instead.
                player_action=autopilot_reason or request.text,
                outcome=outcome,
                change_set=change_set,
                before_facts=before_facts,
                npc_lines=npc_lines,
                world_lines=self._world_lines(change_set, state.player.id),
                recent_narrative=recent_narrative,
                parsed_degraded=parsed.degraded,
                rejected=(
                    None
                    if rule_result.allowed
                    else {
                        "reason_code": str(rule_result.reason_code),
                        "reason": rule_result.reason,
                    }
                ),
                trace=trace,
                debug_requested=request.debug,
                narrative_max_chars=request.narrative_max_chars,
                memory_required=plan.needs_memory and bool(change_set.events),
            )
            try:
                await commit_canonical_turn(
                    uow,
                    session=session,
                    turn_id=turn_id,
                    turn_number=turn_number,
                    player_input=request.text,
                    idempotency_key=request.idempotency_key,
                    world_minute_before=state.world.current_minute,
                    world_minute_after=(
                        state.world.current_minute + outcome.time_cost_minutes
                    ),
                    change_set=change_set,
                    capsule=capsule,
                )
            except Exception as exc:
                trace.errors.append({"code": "COMMIT_FAILED", "message": str(exc)})
                raise

        if not narrate:
            # The world is decided and durable; only the telling is deferred.
            # The trace still lands now, so the debug panel can explain a step
            # whose prose has not been written yet.
            await uow.turns.save_trace(trace.as_dict())
            await uow.commit()
            return TurnResult(
                turn_id=turn_id,
                idempotency_key=request.idempotency_key or turn_id,
                turn_number=turn_number,
                status=TurnStatus.CANONICAL_COMMITTED,
                narrative="",
                degraded=bool(parsed.degraded),
            )

        stored = await uow.turns.get(turn_id)
        assert stored is not None
        return await self._finish_committed_turn(uow, request, session, stored, timer=timer)

    async def _resume_or_replay(
        self,
        uow: UnitOfWork,
        request: TurnRequest,
        session: GameSession,
        stored: dict[str, Any],
    ) -> TurnResult:
        """Replay a completed result or resume presentation after commit."""
        if stored.get("session_id") != request.session_id:
            raise EngineError("idempotency key belongs to another session")
        self._require_same_idempotent_request(request, stored)

        status = TurnStatus(stored.get("status", TurnStatus.COMPLETED))
        if status is TurnStatus.COMPLETED:
            result = stored.get("result") or {}
            if not result:
                raise EngineError("completed turn has no stored result", turn_id=stored.get("id"))
            logger.info("replaying completed turn for idempotency key")
            return TurnResult(**result)
        if status in (TurnStatus.CANONICAL_COMMITTED, TurnStatus.NARRATIVE_FAILED):
            logger.info("resuming narrative for canonically committed turn")
            return await self._finish_committed_turn(uow, request, session, stored)
        raise EngineError("turn is not resumable", turn_id=stored.get("id"), status=str(status))

    async def _finish_committed_turn(
        self,
        uow: UnitOfWork,
        request: TurnRequest,
        session: GameSession,
        stored: dict[str, Any],
        *,
        timer: StageTimer | None = None,
    ) -> TurnResult:
        """Run only post-commit presentation work for a stored canonical turn."""
        stored = await self._ensure_memory_projection(uow, session, stored, timer=timer)
        payload = dict(stored.get("canonical_payload") or {})
        if not payload:
            raise EngineError(
                "committed turn is missing its recovery capsule", turn_id=stored.get("id")
            )

        outcome = ActionOutcome.model_validate(payload["outcome"])
        change_set = ChangeSet.model_validate(payload["change_set"])
        fresh_state = await build_world_state(
            uow, self.d.pack, session.world_id, session.player_character_id
        )
        trace = TurnTrace(**payload.get("trace", {"turn_id": stored["id"]}))
        before_status = TurnStatus(stored.get("status", TurnStatus.CANONICAL_COMMITTED))
        narrative_error: dict[str, Any] = {}

        if timer is not None:
            timer.start("narrate")
        try:
            narrative = await self.d.narrative.render(
                uow,
                fresh_state,
                outcome,
                player_action=str(payload.get("player_action") or stored["player_input"]),
                npc_lines=list(payload.get("npc_lines") or []),
                world_lines=list(payload.get("world_lines") or []),
                recent_narrative=str(payload.get("recent_narrative") or ""),
                max_chars=int(payload.get("narrative_max_chars", DEFAULT_NARRATIVE_CHARS)),
            )
            after_status = TurnStatus.COMPLETED
            trace.narrative_style = narrative.debug
        except Exception as exc:
            # A renderer bug or provider failure is presentation failure only.
            # Return a deterministic factual rendering and leave the turn in a
            # resumable state; the canonical action is never run again.
            logger.exception("narrative failed after canonical commit")
            narrative = NarrativeResult(
                text=self.d.narrative.template.render(
                    fresh_state,
                    outcome,
                    npc_lines=list(payload.get("npc_lines") or []),
                    world_lines=list(payload.get("world_lines") or []),
                ),
                degraded=True,
            )
            narrative_error = {
                "code": "NARRATIVE_FAILED",
                "message": str(exc),
            }
            trace.errors.append(narrative_error)
            after_status = TurnStatus.NARRATIVE_FAILED
        finally:
            if timer is not None:
                timer.stop("narrate")

        # Canonical commit happens before memory projection and narration.
        # Refresh here so the persisted trace, usage ledger, and live evals do
        # not silently omit those paid calls.
        self._refresh_llm_trace(trace)

        require_turn_transition(before_status, after_status)
        if timer is not None:
            trace.stage_timings = timer.timings

        result = TurnResult(
            turn_id=str(stored["id"]),
            idempotency_key=str(stored.get("idempotency_key") or stored["id"]),
            turn_number=int(stored["turn_number"]),
            status=after_status,
            narrative=narrative.text,
            state_changes=self._state_change_summary(
                dict(payload["before_facts"]), fresh_state, change_set
            ),
            visible_updates=fresh_state.scene_summary(),
            choices=self._recommendations(
                fresh_state,
                narrative.beat,
                RuleContext(self.d.pack, fresh_state, GameRNG("choices")),
            ),
            beat=narrative.beat,
            rejected=payload.get("rejected"),
            degraded=(
                bool(payload.get("parsed_degraded"))
                or after_status is TurnStatus.NARRATIVE_FAILED
                or bool(getattr(narrative, "degraded", False))
            ),
        )
        if self.d.debug_mode or request.debug or payload.get("debug_requested"):
            result.debug = trace.as_dict()

        if after_status is TurnStatus.COMPLETED:
            await uow.turns.append_narrative(
                NarrativeSegment(
                    session_id=session.id,
                    turn_id=str(stored["id"]),
                    kind="scene",
                    text=result.narrative,
                    world_minute=fresh_state.world.current_minute,
                )
            )
        payload["trace"] = trace.as_dict()
        await uow.turns.record(
            {
                **stored,
                "status": str(after_status),
                "canonical_payload": payload,
                "last_error": narrative_error,
                "result": result.model_dump(mode="json"),
                "world_minute_after": fresh_state.world.current_minute,
            }
        )
        await uow.turns.save_trace(trace.as_dict())
        await uow.commit()
        return result

    def _require_same_idempotent_request(
        self, request: TurnRequest, stored: dict[str, Any]
    ) -> None:
        """An idempotency key identifies the full request, not just its text."""
        if stored.get("player_input") != request.text:
            raise EngineError(
                "idempotency key was already used for different input",
                turn_id=stored.get("id"),
            )
        payload = dict(stored.get("canonical_payload") or {})
        stored_chars = int(payload.get("narrative_max_chars", DEFAULT_NARRATIVE_CHARS))
        if stored_chars != request.narrative_max_chars:
            raise EngineError(
                "idempotency key was already used with a different narrative length",
                turn_id=stored.get("id"),
                stored_narrative_max_chars=stored_chars,
                requested_narrative_max_chars=request.narrative_max_chars,
            )

    async def _ensure_memory_projection(
        self,
        uow: UnitOfWork,
        session: GameSession,
        stored: dict[str, Any],
        *,
        timer: StageTimer | None = None,
    ) -> dict[str, Any]:
        """Materialise canonical events as memories exactly once.

        This is deliberately a separate post-canonical transaction.  Its
        progress marker and generated rows commit together, so a process crash
        leaves either the whole projection visible or a safely retryable turn.
        """
        payload = dict(stored.get("canonical_payload") or {})
        projection = dict(payload.get("memory_projection") or {})

        # Completed legacy turns predate this marker and must not be projected
        # retroactively.  A legacy committed turn is safe to rebuild because
        # owner/event storage is now idempotent.
        if not projection:
            if TurnStatus(stored.get("status", TurnStatus.COMPLETED)) is TurnStatus.COMPLETED:
                return stored
            change_set = ChangeSet.model_validate(payload["change_set"])
            projection = {
                "status": "PENDING" if change_set.events else "NOT_REQUIRED",
                "attempts": 0,
            }
        if projection.get("status") in {"COMPLETED", "NOT_REQUIRED"}:
            return stored

        change_set = ChangeSet.model_validate(payload["change_set"])
        trace = TurnTrace(**payload.get("trace", {"turn_id": stored["id"]}))
        projection["attempts"] = int(projection.get("attempts", 0)) + 1
        if timer is not None:
            timer.start("memory")
        try:
            state = await build_world_state(
                uow, self.d.pack, session.world_id, session.player_character_id
            )
            cast = await self._cast(uow, state)
            extraction = await self.d.memory.extract(uow, state, change_set.events, owners=cast)
            for memory in extraction.memories:
                await uow.memories.add(memory)
            trace.memory = {
                "stored": len(extraction.memories),
                "skipped": extraction.skipped,
                "degraded": extraction.degraded,
            }
            self._refresh_llm_trace(trace)
            projection.update({"status": "COMPLETED", "last_error": {}})
            payload["memory_projection"] = projection
            payload["trace"] = trace.as_dict()
            await uow.turns.record({**stored, "canonical_payload": payload, "last_error": {}})
            await uow.turns.save_trace(trace.as_dict())
            await uow.commit()
        except Exception as exc:
            await uow.rollback()
            current = await uow.turns.get(str(stored["id"]))
            if current is None:
                raise EngineError(
                    "memory projection failed and committed turn disappeared",
                    turn_id=stored.get("id"),
                ) from exc
            failed_payload = dict(current.get("canonical_payload") or payload)
            failed_projection = dict(failed_payload.get("memory_projection") or projection)
            error = {"code": "MEMORY_PROJECTION_FAILED", "message": str(exc)}
            failed_projection.update(
                {
                    "status": "FAILED",
                    "attempts": int(projection["attempts"]),
                    "last_error": error,
                }
            )
            failed_payload["memory_projection"] = failed_projection
            await uow.turns.record(
                {**current, "canonical_payload": failed_payload, "last_error": error}
            )
            await uow.commit()
            raise EngineError(
                "memory projection failed after canonical commit",
                turn_id=stored.get("id"),
            ) from exc
        finally:
            if timer is not None:
                timer.stop("memory")

        refreshed = await uow.turns.get(str(stored["id"]))
        if refreshed is None:
            raise EngineError("committed turn disappeared", turn_id=stored.get("id"))
        return refreshed

    # ==================================================================
    def _plan(self, action: Action, state: WorldStateView) -> OrchestratorPlan:
        if action.action_type in QUERY_ACTIONS:
            return OrchestratorPlan.for_query()
        plan = OrchestratorPlan()
        if not [c for c in state.present_characters if c.alive]:
            plan.needs_npcs = False
        return plan

    async def _run_npcs(
        self,
        uow: UnitOfWork,
        ctx: RuleContext,
        action: Action,
        outcome: ActionOutcome,
        change_set: ChangeSet,
        trace: TurnTrace,
    ) -> list[str]:
        """Compatibility facade; the phase itself lives in ``NpcPhase``."""
        return await self.npc_phase.run(uow, ctx, action, outcome, change_set, trace)

    # ==================================================================
    def _new_tension(
        self,
        state: WorldStateView,
        outcome: ActionOutcome,
        director_result,
        simulation_report,
    ) -> float:
        days = (
            outcome.time_cost_minutes / state.clock.minutes_per_day
            if outcome.time_cost_minutes
            else 0.0
        )
        value = self.tension.apply(
            state.world.narrative_tension, days_elapsed=days, importance=outcome.importance
        )
        if (
            director_result is not None
            and director_result.validation.accepted
            and director_result.decision.schedule_after_minutes == 0
        ):
            value = max(
                0.0,
                min(100.0, value + director_result.decision.tension_delta),
            )
        if simulation_report is not None and simulation_report.director_tension_delta:
            value = max(
                0.0,
                min(100.0, value + simulation_report.director_tension_delta),
            )
        return value

    def _world_lines(self, change_set: ChangeSet, player_id: str) -> list[str]:
        lines: list[str] = []
        for event in change_set.events:
            participants = set(event.target_ids) | ({event.actor_id} if event.actor_id else set())
            if (
                event.visibility in (Visibility.PRIVATE, Visibility.SECRET)
                and player_id not in participants
                and player_id not in event.witnesses
            ):
                continue
            if event.event_type in ("REJECTED_ACTION", "OBSERVATION"):
                continue
            summary = event.payload.get("summary")
            if isinstance(summary, str) and summary:
                lines.append(summary)
                continue
            if event.event_type == "DEATH" and event.payload.get("cause") == "natural_lifespan":
                template = str(
                    self.d.pack.narrative_templates.get("world_event", {}).get("natural_death", "")
                )
                if template:
                    lines.append(template.format(name=str(event.payload.get("character_name", ""))))
        return lines[-3:]

    _TRACKED_FIELDS = (
        "alive",
        "age",
        "health",
        "spiritual_power",
        "cultivation_progress",
        "injuries",
        "mental_state",
    )

    def _capture(self, state: WorldStateView) -> dict[str, Any]:
        """Freeze the values a turn diff is computed against."""
        ladder = self.d.pack.realms
        player = state.player
        return {
            "player": {field: getattr(player, field) for field in self._TRACKED_FIELDS},
            "realm": ladder.display(player.realm, player.realm_stage),
            "realm_key": (player.realm, player.realm_stage),
            "location_id": player.location_id,
            "location_name": state.location.name if state.location else None,
            "world_minute": state.world.current_minute,
            "time_label": state.time.label,
            "narrative_tension": state.world.narrative_tension,
        }

    def _state_change_summary(
        self, before: dict[str, Any], after: WorldStateView, change_set: ChangeSet
    ) -> dict[str, Any]:
        ladder = self.d.pack.realms
        p1 = after.player
        character: dict[str, Any] = {}
        for field_name in self._TRACKED_FIELDS:
            a, b = before["player"][field_name], getattr(p1, field_name)
            if a != b:
                character[field_name] = [a, b]
        if before["realm_key"] != (p1.realm, p1.realm_stage):
            character["realm"] = [before["realm"], ladder.display(p1.realm, p1.realm_stage)]
        if before["location_id"] != p1.location_id:
            character["location"] = [
                before["location_name"],
                after.location.name if after.location else None,
            ]

        # Item keys are engine plumbing; the player is shown the item's name.
        inventory: dict[str, list[dict[str, Any]]] = {"added": [], "removed": []}
        for change in change_set.changes:
            if change.kind not in (
                mut.ChangeKind.INVENTORY_ADD,
                mut.ChangeKind.INVENTORY_REMOVE,
            ):
                continue
            entry = {
                **change.payload,
                "name": after.item_name(str(change.payload.get("item_key", ""))),
            }
            bucket = "added" if change.kind is mut.ChangeKind.INVENTORY_ADD else "removed"
            inventory[bucket].append(entry)

        relationships = [
            {
                "with": change.payload.get("other_id"),
                "with_name": (
                    c.display_name
                    if (c := after.character_by_id(change.payload.get("other_id")))
                    else ""
                ),
                "deltas": change.payload.get("deltas"),
                "reason": change.reason,
            }
            for change in change_set.by_kind(mut.ChangeKind.RELATIONSHIP_DELTA)
        ]

        return {
            "character": character,
            "inventory": inventory,
            "relationships": relationships,
            "world_minute": [before["world_minute"], after.world.current_minute],
            "time_label": [before["time_label"], after.time.label],
            "narrative_tension": [
                round(before["narrative_tension"], 1),
                round(after.world.narrative_tension, 1),
            ],
            "events": [e.event_type for e in change_set.events],
        }

    def _recommendations(
        self,
        state: WorldStateView,
        beat: StoryBeat | None,
        ctx: RuleContext,
    ) -> list[Choice]:
        """Prefer the narrator's just-written hand-off over generic fallbacks.

        The beat is produced from the completed chapter and therefore knows
        who just spoke, what changed, and which decision is actually pending.
        Persisting it as ``choices`` keeps history, recap, and a freshly loaded
        page on the same recommendations the player saw at the end of the turn.
        """
        if beat is not None and beat.options:
            return beat.options
        return self._choices(state, ctx)

    def _choices(self, state: WorldStateView, ctx: RuleContext) -> list[Choice]:
        """Suggestions only. Free-text input is always available."""
        choices: list[Choice] = []
        for npc in state.present_characters[:3]:
            if npc.alive:
                choices.append(
                    Choice(
                        label=npc.display_name,
                        hint=str(ActionType.TALK),
                        action_type=str(ActionType.TALK),
                    )
                )
        for key in list(state.graph.neighbours(state.location_key()))[:3]:
            location = state.graph.by_key(key)
            if location is not None and location.accessible:
                choices.append(
                    Choice(
                        label=location.name,
                        hint=str(ActionType.MOVE),
                        action_type=str(ActionType.MOVE),
                    )
                )
        choices.append(
            Choice(label="", hint=str(ActionType.CULTIVATE), action_type=str(ActionType.CULTIVATE))
        )
        return choices[:8]

    # ==================================================================
    async def _notify(self, on_step: StepListener | None, index: int, step: ChapterStep) -> None:
        """Progress reporting must never be able to break the run."""
        if on_step is None:
            return
        try:
            await on_step(index, step)
        except Exception:  # a dropped client is not a game error
            logger.debug("step listener failed; the run continues", exc_info=True)

    def _advance_budget(self) -> AdvanceBudget:
        return AdvanceBudget(
            max_steps=max(1, int(self.d.pack.rule("auto_advance.max_steps", 5))),
            max_minutes=max(1, int(self.d.pack.rule("auto_advance.max_minutes", 720))),
        )

    async def _advance_step(
        self,
        uow: UnitOfWork,
        request: TurnRequest,
        session: GameSession,
        request_id: str,
        timer: StageTimer,
        *,
        text: str = "",
        forced_intent: PlayerIntent | None = None,
        idempotency_key: str | None = None,
    ) -> StepOutcome:
        """Commit one step of a run and decide whether it ended the run."""
        d = self.d
        before = await build_world_state(uow, d.pack, session.world_id, session.player_character_id)
        health_before = before.player.health
        present_before = list(before.present_characters)

        turn_id = str(uuid.uuid4())
        # For a player-led step ``text`` is the request.  For a bare
        # "continue" the first step is forced by the autopilot, but the row
        # carrying the run's idempotency key must still preserve the original
        # request identity so a retry can validate and replay it.
        stored_text = text or (request.text if idempotency_key else "")
        step_request = request.model_copy(
            update={"text": stored_text, "idempotency_key": idempotency_key}
        )
        result = await self._run(
            uow,
            step_request,
            session,
            turn_id,
            request_id,
            timer,
            narrate=False,
            forced_intent=forced_intent,
        )
        if result.status is not TurnStatus.CANONICAL_COMMITTED:
            # The only way here is unreadable input, which commits nothing.
            return StepOutcome(clarification=result)

        stored = await uow.turns.get(turn_id)
        assert stored is not None
        # A multi-step chapter postpones prose, not canonical projections.
        # Every step may create events known to an NPC, so project those
        # memories before the run can mark the turn complete.
        stored = await self._ensure_memory_projection(uow, session, stored, timer=timer)
        payload = dict(stored.get("canonical_payload") or {})
        outcome = ActionOutcome.model_validate(payload["outcome"])
        change_set = ChangeSet.model_validate(payload["change_set"])
        trace = dict(payload.get("trace") or {})

        after = await build_world_state(uow, d.pack, session.world_id, session.player_character_id)
        interrupt = d.interrupts.detect(
            after,
            outcome=outcome,
            change_set=change_set,
            npc_decisions=list(trace.get("npc_decisions") or []),
            present=present_before,
            health_before=health_before,
            director=trace.get("director"),
        )
        return StepOutcome(
            turn_id=turn_id,
            step=ChapterStep(
                action=str(payload.get("player_action") or text or ""),
                outcome=outcome,
                npc_lines=list(payload.get("npc_lines") or []),
                world_lines=list(payload.get("world_lines") or []),
                by_player=bool(text),
                minutes=outcome.time_cost_minutes,
            ),
            interrupt=interrupt,
            degraded=result.degraded,
        )

    async def _close_run(
        self,
        uow: UnitOfWork,
        session: GameSession,
        request: TurnRequest,
        state: WorldStateView,
        *,
        turn_ids: list[str],
        chapter: ChapterResult,
        interrupt: Interrupt,
        timer: StageTimer,
        degraded: bool,
        llm_calls: list[dict[str, Any]],
    ) -> TurnResult:
        """Complete every turn in the run and attach the chapter to its first.

        A run is identified by the step that started it - the one the player
        asked for. That is the row carrying the idempotency key, so it is also
        where the result and the trace have to live for a retry to replay the
        whole run instead of re-running it.

        The chapter is one narrative segment covering all the steps, so the
        next turn's context reads it as one continuous story rather than a
        stack of fragments.
        """
        head_id = turn_ids[0]
        result = TurnResult(
            turn_id=head_id,
            idempotency_key=request.idempotency_key or head_id,
            turn_number=session.turn_number,
            status=TurnStatus.COMPLETED,
            narrative=chapter.text,
            state_changes=await self._run_state_changes(uow, turn_ids, state),
            visible_updates=state.scene_summary(),
            choices=self._recommendations(
                state,
                chapter.beat,
                RuleContext(self.d.pack, state, GameRNG("choices")),
            ),
            beat=chapter.beat,
            interrupt=interrupt.as_dict(),
            steps=len(turn_ids),
            degraded=degraded,
        )
        if self.d.debug_mode or request.debug:
            # The run's own trace, on top of the first step's - which is the
            # one that explains what the player actually asked for.
            first = await uow.turns.get(turn_ids[0])
            base = dict((first or {}).get("canonical_payload") or {}).get("trace") or {}
            result.debug = {
                **base,
                "turn_id": head_id,
                "turn_ids": turn_ids,
                "stage_timings": {**base.get("stage_timings", {}), **timer.timings},
                "interrupt": interrupt.as_dict(),
                "chapter": chapter.debug,
                "llm_calls": llm_calls,
                "token_usage": {
                    "prompt": sum(int(call.get("prompt_tokens", 0)) for call in llm_calls),
                    "completion": sum(int(call.get("completion_tokens", 0)) for call in llm_calls),
                },
            }

        for turn_id in turn_ids:
            stored = await uow.turns.get(turn_id)
            if stored is None:
                continue
            before_status = TurnStatus(stored.get("status", TurnStatus.CANONICAL_COMMITTED))
            if before_status is TurnStatus.COMPLETED:
                continue
            require_turn_transition(before_status, TurnStatus.COMPLETED)
            is_head = turn_id == head_id
            await uow.turns.record(
                {
                    **stored,
                    "status": str(TurnStatus.COMPLETED),
                    "result": result.model_dump(mode="json") if is_head else {},
                    "world_minute_after": state.world.current_minute,
                }
            )
            if is_head and result.debug is not None:
                await uow.turns.save_trace(result.debug)

        await uow.turns.append_narrative(
            NarrativeSegment(
                session_id=session.id,
                turn_id=head_id,
                kind="chapter",
                text=chapter.text,
                world_minute=state.world.current_minute,
            )
        )
        await uow.commit()
        return result

    async def _run_state_changes(
        self, uow: UnitOfWork, turn_ids: list[str], state: WorldStateView
    ) -> dict[str, Any]:
        """Player-visible deltas across the whole run, not just its last step.

        A chapter that quietly cost you a third of your health should say so
        once, for the whole chapter - so the baseline is the run's first step.
        """
        first = await uow.turns.get(turn_ids[0])
        payload = dict((first or {}).get("canonical_payload") or {})
        before = payload.get("before_facts")
        if not before:
            return {"steps": len(turn_ids)}

        merged = ChangeSet()
        for turn_id in turn_ids:
            stored = await uow.turns.get(turn_id)
            capsule = dict((stored or {}).get("canonical_payload") or {})
            if capsule.get("change_set"):
                merged.changes.extend(ChangeSet.model_validate(capsule["change_set"]).changes)
        summary = self._state_change_summary(dict(before), state, merged)
        summary["steps"] = len(turn_ids)
        return summary

    def _is_continue(self, text: str) -> bool:
        """Did the player ask the story to carry on by itself?

        The trigger words are content, like every other piece of language in
        this engine.
        """
        stripped = (text or "").strip()
        if not stripped:
            return False
        words = self.d.pack.vocabulary.get("continue_words", []) or []
        return any(word and stripped == word for word in words)

    async def _autopilot_intent(
        self, autopilot: Autopilot, state: WorldStateView, recent_narrative: str
    ) -> tuple[ParsedIntent, str]:
        intent, reason = await autopilot.choose(state, recent_narrative=recent_narrative)
        action, plan, notes = self.d.intent_parser.resolve(state, intent)
        return (
            ParsedIntent(
                intent=intent,
                action=action,
                plan=plan,
                degraded=not autopilot.usable(),
                resolution_notes=notes,
            ),
            reason,
        )

    async def _run_steward(
        self,
        steward: WorldSteward,
        state: WorldStateView,
        parsed,
        world_characters: list[Character],
        recent_narrative: str,
    ) -> StewardResult:
        """Recognise what the player meant; only invent what is really absent.

        The cheap deterministic pass runs first because most 'missing' things
        are not missing at all - they are the main hall the player called 大殿,
        or a character standing one room away.
        """
        still_missing: list[str] = []
        result = StewardResult()
        for phrase in parsed.unresolved:
            location = steward.recognise_location(state, phrase)
            if location is not None:
                result.location_key = location.key
                result.notes.append(f"recognised_location:{phrase}->{location.key}")
                continue
            character = steward.recognise_character(state, phrase, world_characters)
            if character is not None:
                result.target_id = character.id
                result.target_key = character.key
                if not state.is_present(character.id) and not result.location_key:
                    result.location_key = character.location_key
                result.notes.append(f"recognised_character:{phrase}->{character.key}")
                continue
            still_missing.append(phrase)

        if not still_missing:
            return result

        invented = await steward.resolve(
            state,
            player_text=parsed.intent.raw_text,
            unresolved=still_missing,
            world_characters=world_characters,
            recent_narrative=recent_narrative,
        )
        # Anything the deterministic pass already pinned down wins: it matched
        # something the world actually has.
        invented.notes = [*result.notes, *invented.notes]
        invented.location_key = result.location_key or invented.location_key
        if result.target_id:
            invented.target_id = result.target_id
            invented.target_key = result.target_key
        return invented

    def _extend_state(self, state: WorldStateView, steward: StewardResult) -> WorldStateView:
        """Make freshly created entities visible for the rest of this turn.

        They are already in the change set headed for the database; this keeps
        the in-memory snapshot from lagging a turn behind it.
        """
        locations = state.graph.all() + steward.new_locations
        graph = LocationGraph(locations)
        present = list(state.present_characters)
        present += [c for c in steward.new_characters if c.location_id == state.player.location_id]
        return replace(
            state,
            graph=graph,
            location=graph.by_id(state.player.location_id),
            present_characters=present,
        )

    # ==================================================================
    async def _clarification_turn(
        self,
        uow: UnitOfWork,
        session: GameSession,
        state: WorldStateView,
        turn_id: str,
        turn_number: int,
        parsed,
        trace: TurnTrace,
        timer: StageTimer,
        request: TurnRequest,
    ) -> TurnResult:
        """Unreadable input costs the player nothing - not even world time.

        The player never sees a reason code for this. They see a scene that
        did not move, and a few things they could do instead: an engine that
        cannot read a line is the engine's problem, not an accusation.
        """
        outcome = ActionOutcome(
            action_type=ActionType.CUSTOM,
            success=False,
            summary_key="idle",
            facts={},
        )
        text = self.d.narrative.template.render(state, outcome)
        trace.stage_timings = timer.timings
        result = TurnResult(
            turn_id=turn_id,
            idempotency_key=request.idempotency_key or turn_id,
            turn_number=turn_number,
            status=TurnStatus.COMPLETED,
            narrative=text,
            state_changes={},
            visible_updates=state.scene_summary(),
            choices=self._choices(state, RuleContext(self.d.pack, state, GameRNG("clarify"))),
            degraded=parsed.degraded,
        )
        if self.d.debug_mode or request.debug:
            result.debug = trace.as_dict()
        session.turn_number = turn_number
        await uow.sessions.save(session)
        await uow.turns.record(
            {
                "id": turn_id,
                "session_id": session.id,
                "turn_number": turn_number,
                "player_input": request.text,
                "idempotency_key": request.idempotency_key or turn_id,
                "status": str(TurnStatus.COMPLETED),
                "world_minute_before": state.world.current_minute,
                "world_minute_after": state.world.current_minute,
                "canonical_payload": {},
                "last_error": {},
                "result": result.model_dump(mode="json"),
            }
        )
        await uow.turns.save_trace(trace.as_dict())
        await uow.commit()
        return result

    async def _idle_turn(
        self,
        uow: UnitOfWork,
        session: GameSession,
        state: WorldStateView,
        request: TurnRequest,
        request_id: str,
    ) -> TurnResult:
        """A run that committed nothing. The scene holds; no time passes."""
        turn_id = str(uuid.uuid4())
        trace = TurnTrace(
            turn_id=turn_id,
            request_id=request_id,
            session_id=session.id,
            world_id=session.world_id,
        )
        parsed = SimpleNamespace(degraded=True)
        return await self._clarification_turn(
            uow,
            session,
            state,
            turn_id,
            session.turn_number + 1,
            parsed,
            trace,
            StageTimer(),
            request,
        )

    async def _recent_narrative(self, uow: UnitOfWork, session_id: str, limit: int = 4) -> str:
        segments = await uow.turns.list_narrative(session_id, limit=limit)
        return "\n\n".join(s.text for s in segments if s.text and s.kind != BEAT_SEGMENT)

    async def _pending_beat(self, uow: UnitOfWork, session_id: str) -> str:
        """What the last chapter left hanging, as plain text.

        The player is answering this, so the parser needs it in front of it -
        otherwise a line like "去看看写的什么" has no antecedent and the turn
        wanders off to whatever the character's standing goals suggest.
        """
        turns = await uow.turns.list_for_session(session_id, limit=6)
        for turn in reversed(turns):
            rendered = self._render_beat((turn.get("result") or {}).get("beat") or {})
            if rendered:
                return rendered

        # No turn carries one yet, which means the player is answering the
        # opening chapter - whose beat is recorded as a narrative segment.
        segments = await uow.turns.list_narrative(session_id, limit=6)
        for segment in reversed(segments):
            if segment.kind != BEAT_SEGMENT:
                continue
            try:
                rendered = self._render_beat(json.loads(segment.text))
            except (json.JSONDecodeError, TypeError):
                continue
            if rendered:
                return rendered
        return ""

    @staticmethod
    def _render_beat(beat: dict[str, Any]) -> str:
        question = str(beat.get("question") or "").strip()
        options = [
            str(o.get("label", "")).strip()
            for o in (beat.get("options") or [])
            if str(o.get("label", "")).strip()
        ]
        if not (question or options):
            return ""
        # Neutral assembly; the prompt supplies the wording around it.
        parts = [question] if question else []
        if options:
            parts.append("[" + " | ".join(options) + "]")
        return " ".join(parts)

    async def _turns_since_director(self, uow: UnitOfWork, session: GameSession) -> int:
        last = await uow.director_events.last_for_session(session.id)
        if last is None:
            return session.turn_number
        return max(0, session.turn_number - last.created_turn_number)

    def _projected_state(
        self,
        state: WorldStateView,
        change_set: ChangeSet,
        elapsed_minutes: int,
    ) -> WorldStateView:
        """Director sees the time/location the resolved action actually reaches."""
        target_minute = state.world.current_minute + max(0, elapsed_minutes)
        world = state.world.model_copy(update={"current_minute": target_minute})
        player = state.player.model_copy(deep=True)
        location = state.location
        for change in change_set.by_kind(mut.ChangeKind.CHARACTER_LOCATION):
            if change.target_id != player.id:
                continue
            player.location_id = str(change.after)
            location = state.graph.by_id(str(change.after))
            player.location_key = location.key if location else None
        return replace(
            state,
            world=world,
            time=state.clock.to_world_time(target_minute),
            player=player,
            location=location,
        )

    async def _cast(self, uow: UnitOfWork, state: WorldStateView) -> list[Character]:
        people = await uow.characters.list_for_world(state.world.id, alive_only=False)
        return [
            c
            for c in people
            if c.character_type is not CharacterType.BACKGROUND or c.id == state.player.id
        ]

    def _refresh_llm_trace(self, trace: TurnTrace) -> None:
        if self.d.llm is None:
            return
        trace.llm_calls = record_llm_calls(self.d.llm.records)
        usage = self.d.llm.total_usage()
        trace.token_usage = {
            "prompt": usage.prompt_tokens,
            "completion": usage.completion_tokens,
        }

    def importance_band(self, importance: float):
        return band_for_importance(importance)

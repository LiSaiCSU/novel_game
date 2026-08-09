"""GameOrchestrator - the turn scheduler (Prompt section 6).

It writes no prose and decides no outcomes. It sequences the subsystems, holds
the transaction boundary, enforces idempotency, budgets AI calls, and records
what happened.

Stage order (see docs/GAME_LOOP.md):
    ingest, snapshot, intent, plan, validate, resolve, npc, simulate, direct,
    validate2, guard, commit, memory, narrate, respond
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from engine.actions.intent_parser import IntentParser
from engine.actions.resolver import ActionResolver
from engine.actions.schema import Action, ActionOutcome
from engine.characters.npc_agent import NPCAgent, NPCSituation
from engine.contentpack.pack import ContentPack
from engine.context.builder import ContextBuilder
from engine.core import mutations as mut
from engine.core.errors import ConsistencyViolation, EngineError
from engine.core.locks import IdempotencyStore, LockBackend
from engine.core.logging import bind, get_logger
from engine.core.models import Character, GameSession, NarrativeSegment
from engine.core.mutations import ChangeSet
from engine.core.ports import UnitOfWork
from engine.core.types import QUERY_ACTIONS, ActionType, CharacterType, ReasonCode
from engine.director.director import Director
from engine.director.tension import TensionModel
from engine.events.builder import EventBuilder
from engine.knowledge.service import KnowledgeService
from engine.memory.extractor import MemoryExtractor
from engine.narrative.renderer import NarrativeRenderer
from engine.orchestrator.proposals import ProposalValidator
from engine.orchestrator.turn import (
    Choice,
    OrchestratorPlan,
    StageTimer,
    TurnRequest,
    TurnResult,
    TurnTrace,
    record_llm_calls,
    record_rng,
)
from engine.relationships.manager import RelationshipManager, band_for_importance
from engine.rng.game_rng import GameRNG, event_rng
from engine.rules.base import RuleContext
from engine.rules.engine import RuleEngine
from engine.simulation.simulator import WorldSimulator
from engine.world.consistency import ConsistencyGuard
from engine.world.state_view import WorldStateView, build_world_state

logger = get_logger("orchestrator")


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
    llm: Any | None = None
    locks: LockBackend | None = None
    idempotency: IdempotencyStore | None = None
    debug_mode: bool = True


class GameOrchestrator:
    def __init__(self, deps: OrchestratorDeps) -> None:
        self.d = deps
        self.tension = TensionModel(deps.pack)
        self.proposals = ProposalValidator(deps.pack, deps.relationships)

    # ==================================================================
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
                    logger.info("replaying stored turn for idempotency key")
                    return TurnResult(**existing["result"])

        lock = self.d.locks
        if lock is None:
            return await self._run(uow, request, session, turn_id, request_id, timer)
        async with lock.acquire(f"world:{session.world_id}"):
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
    ) -> TurnResult:
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
            rng = event_rng(
                state.world.world_seed, session.session_seed, f"turn-{turn_number}"
            )
            ctx = RuleContext(pack=d.pack, state=state, rng=rng)
            recent_narrative = await self._recent_narrative(uow, session.id)
            # Snapshot primitives, not object references: after commit the
            # repository may hand back the very objects this view was built
            # from, and a before/after diff of one object is always empty.
            before_facts = self._capture(state)

        # -- S2 intent ------------------------------------------------------
        with timer.measure("intent"):
            parsed = await d.intent_parser.parse(
                uow, state, request.text, recent_narrative=recent_narrative
            )
            trace.intent = {
                **parsed.intent.model_dump(mode="json"),
                "degraded": parsed.degraded,
                "resolution_notes": parsed.resolution_notes,
            }

        # Ambiguous input: ask, do not guess, and do not move the clock.
        if parsed.intent.needs_clarification() and parsed.action.action_type is ActionType.CUSTOM:
            return await self._clarification_turn(
                uow, session, state, turn_id, turn_number, parsed, trace, timer, request
            )

        action = parsed.action

        # -- S3 plan --------------------------------------------------------
        with timer.measure("plan"):
            plan = self._plan(action, state)
            trace.stage_timings["plan"] = 0

        # -- S4 validate ----------------------------------------------------
        with timer.measure("validate"):
            rule_result = d.rules.validate_action(ctx, action)
            trace.rule_result = rule_result.model_dump(mode="json")
            if not rule_result.allowed:
                plan = OrchestratorPlan.for_rejection()

        # -- S5 resolve -----------------------------------------------------
        with timer.measure("resolve"):
            event_builder = EventBuilder(d.pack, state.world.id, turn_id=turn_id)
            resolver = ActionResolver(event_builder, d.relationships)
            outcome, change_set = resolver.resolve(ctx, action, rule_result)
            trace.outcome = outcome.model_dump(mode="json")

        # -- S6 npc ---------------------------------------------------------
        # Decisions themselves land in the trace; only the spoken lines flow on
        # to the narrative stage.
        npc_lines: list[str] = []
        if plan.needs_npcs:
            with timer.measure("npc"):
                npc_lines = await self._run_npcs(
                    uow, ctx, action, outcome, change_set, trace
                )

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
        if plan.needs_director:
            with timer.measure("direct"):
                turns_since = await self._turns_since_director(uow, session.id)
                director_result = await d.director.direct(
                    uow,
                    state,
                    turns_since_last_event=turns_since,
                    last_turn_importance=outcome.importance,
                    rng=rng.derive("director"),
                )
                trace.director = {
                    "decision": director_result.decision.model_dump(mode="json"),
                    "consulted": director_result.consulted,
                    "degraded": director_result.degraded,
                    "skip_reason": director_result.skip_reason,
                    "rejections": director_result.validation.rejections,
                    "debug": director_result.debug,
                }

        # -- S9 validate2: AI proposals become state, or do not ---------------
        with timer.measure("validate2"):
            if director_result is not None and director_result.validation.accepted:
                report = await self.proposals.apply_director_decision(
                    uow,
                    state,
                    director_result.decision,
                    change_set,
                    event_builder=event_builder,
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
            try:
                await uow.apply(change_set)
                await uow.commit()
            except Exception as exc:
                await uow.rollback()
                trace.errors.append({"code": "COMMIT_FAILED", "message": str(exc)})
                logger.error("commit failed, turn rolled back: %s", exc)
                raise

        # -- S12 memory (outside the world transaction) ----------------------
        if plan.needs_memory and change_set.events:
            with timer.measure("memory"):
                cast = await self._cast(uow, state)
                extraction = await d.memory.extract(uow, state, change_set.events, owners=cast)
                for memory in extraction.memories:
                    await uow.memories.add(memory)
                trace.memory = {
                    "stored": len(extraction.memories),
                    "skipped": extraction.skipped,
                    "degraded": extraction.degraded,
                }

        # -- S13 narrate ----------------------------------------------------
        with timer.measure("narrate"):
            fresh_state = await build_world_state(
                uow, d.pack, session.world_id, session.player_character_id
            )
            world_lines = self._world_lines(change_set)
            narrative = await d.narrative.render(
                uow,
                fresh_state,
                outcome,
                player_action=request.text,
                npc_lines=npc_lines,
                world_lines=world_lines,
                recent_narrative=recent_narrative,
            )
            trace.narrative_style = narrative.debug

        # -- S14 respond ----------------------------------------------------
        with timer.measure("respond"):
            session.turn_number = turn_number
            await uow.sessions.save(session)
            await uow.turns.append_narrative(
                NarrativeSegment(
                    session_id=session.id,
                    turn_id=turn_id,
                    kind="scene",
                    text=narrative.text,
                    world_minute=fresh_state.world.current_minute,
                )
            )

            result = TurnResult(
                turn_id=turn_id,
                turn_number=turn_number,
                narrative=narrative.text,
                state_changes=self._state_change_summary(before_facts, fresh_state, change_set),
                visible_updates=fresh_state.scene_summary(),
                choices=self._choices(fresh_state, ctx),
                rejected=(
                    None
                    if rule_result.allowed
                    else {
                        "reason_code": str(rule_result.reason_code),
                        "reason": rule_result.reason,
                    }
                ),
                degraded=parsed.degraded or narrative.degraded,
            )

            trace.stage_timings = timer.timings
            trace.rng_traces = record_rng(rng.traces)
            if d.llm is not None:
                trace.llm_calls = record_llm_calls(d.llm.records)
                usage = d.llm.total_usage()
                trace.token_usage = {
                    "prompt": usage.prompt_tokens,
                    "completion": usage.completion_tokens,
                }
            if d.debug_mode or request.debug:
                result.debug = trace.as_dict()

            await uow.turns.record(
                {
                    "id": turn_id,
                    "session_id": session.id,
                    "turn_number": turn_number,
                    "player_input": request.text,
                    "idempotency_key": request.idempotency_key,
                    "world_minute_before": state.world.current_minute,
                    "world_minute_after": fresh_state.world.current_minute,
                    "result": result.model_dump(mode="json"),
                }
            )
            await uow.turns.save_trace(trace.as_dict())
            await uow.commit()
        return result

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
        """Run every present NPC's decision, validate it, and collect what was said."""
        d = self.d
        state = ctx.state
        present = [c for c in state.present_characters if c.alive]
        if not present:
            return []

        referenced = await d.knowledge.match_facts(
            uow, state.world.id, action.utterance or action.raw_text
        )
        lines: list[str] = []
        for npc in present:
            situation = NPCSituation(
                player_action=action.action_type,
                is_target=action.target_id == npc.id,
                utterance=action.utterance,
                method=action.method,
                request_size=action.request_size,
                topic=action.goal.topic,
                referenced_facts=referenced if action.target_id == npc.id else [],
                summary=outcome.summary_key,
            )
            available = d.rules.available_actions(ctx, npc.id)
            result = await d.npc_agent.decide(uow, ctx, npc, situation, available)
            report = await self.proposals.apply_npc_decision(
                uow,
                state,
                result,
                change_set,
                importance=outcome.importance,
                available_actions=available,
            )
            trace.npc_decisions.append(
                {
                    "npc": npc.key,
                    "degraded": result.degraded,
                    "reasons": result.reasons,
                    "decision": result.decision.model_dump(mode="json"),
                    "proposals": report.as_dict(),
                    "context_tokens": result.context.estimated_tokens if result.context else 0,
                }
            )
            if result.context is not None:
                trace.context_snapshots[f"npc:{npc.key}"] = result.context.as_dict()

            if result.decision.speech_intent or result.decision.spoken_line:
                lines.append(
                    d.narrative.npc_line(
                        npc, result.decision.speech_intent, result.decision.spoken_line
                    )
                )
        return [line for line in lines if line]

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
        if director_result is not None and director_result.validation.accepted:
            value = max(0.0, min(100.0, value + director_result.decision.tension_delta))
        return value

    def _world_lines(self, change_set: ChangeSet) -> list[str]:
        lines: list[str] = []
        for event in change_set.events:
            if event.event_type in ("REJECTED_ACTION", "OBSERVATION"):
                continue
            summary = event.payload.get("summary")
            if isinstance(summary, str) and summary:
                lines.append(summary)
        return lines[-3:]

    _TRACKED_FIELDS = (
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

        inventory: dict[str, list[dict[str, Any]]] = {"added": [], "removed": []}
        for change in change_set.changes:
            if change.kind is mut.ChangeKind.INVENTORY_ADD:
                inventory["added"].append(change.payload)
            elif change.kind is mut.ChangeKind.INVENTORY_REMOVE:
                inventory["removed"].append(change.payload)

        relationships = [
            {
                "with": change.payload.get("other_id"),
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
        """Unparseable input costs the player nothing - not even world time."""
        outcome = ActionOutcome(
            action_type=ActionType.CUSTOM,
            success=False,
            summary_key="rejected",
            facts={
                "reason_code": str(ReasonCode.AMBIGUOUS_INTENT),
                "ambiguity": parsed.intent.ambiguity or "",
            },
        )
        text = self.d.narrative.template.render(state, outcome)
        trace.stage_timings = timer.timings
        result = TurnResult(
            turn_id=turn_id,
            turn_number=session.turn_number,
            narrative=text,
            state_changes={},
            visible_updates=state.scene_summary(),
            choices=self._choices(state, RuleContext(self.d.pack, state, GameRNG("clarify"))),
            rejected={
                "reason_code": str(ReasonCode.AMBIGUOUS_INTENT),
                "reason": parsed.intent.ambiguity or "",
            },
            degraded=parsed.degraded,
        )
        if self.d.debug_mode or request.debug:
            result.debug = trace.as_dict()
        return result

    async def _recent_narrative(self, uow: UnitOfWork, session_id: str, limit: int = 3) -> str:
        segments = await uow.turns.list_narrative(session_id, limit=limit)
        return "\n\n".join(s.text for s in segments if s.text)

    async def _turns_since_director(self, uow: UnitOfWork, session_id: str) -> int:
        turns = await uow.turns.list_for_session(session_id, limit=20)
        count = 0
        for turn in reversed(turns):
            debug = (turn.get("result") or {}).get("debug") or {}
            director = debug.get("director") or {}
            decision = (director.get("decision") or {}).get("decision")
            if decision and decision != "NO_EVENT":
                break
            count += 1
        return count

    async def _cast(self, uow: UnitOfWork, state: WorldStateView) -> list[Character]:
        people = await uow.characters.list_for_world(state.world.id, alive_only=False)
        return [
            c
            for c in people
            if c.character_type is not CharacterType.BACKGROUND or c.id == state.player.id
        ]

    def importance_band(self, importance: float):
        return band_for_importance(importance)

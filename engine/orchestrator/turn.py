"""Turn-level data structures and observability records (Prompt section 60)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from engine.actions.schema import Action, ActionOutcome, PlayerIntent, RuleResult
from engine.llm.provider import LLMCallRecord
from engine.rng.game_rng import RngTrace

# Narrative length is a presentation preference, but once a canonical turn is
# committed the preference belongs to that request.  A retry may rewrite the
# prose; it may not silently turn the same idempotent request into a different
# chapter contract.
MIN_NARRATIVE_CHARS = 400
DEFAULT_NARRATIVE_CHARS = 1800
MAX_NARRATIVE_CHARS = 4000


class TurnStatus(StrEnum):
    """Persisted turn lifecycle.

    A turn becomes recoverable at ``CANONICAL_COMMITTED``: from that point on
    its action must never be resolved again.  Only presentation work may be
    retried.
    """

    CANONICAL_COMMITTED = "CANONICAL_COMMITTED"
    NARRATIVE_FAILED = "NARRATIVE_FAILED"
    COMPLETED = "COMPLETED"


_TURN_TRANSITIONS: dict[TurnStatus, frozenset[TurnStatus]] = {
    TurnStatus.CANONICAL_COMMITTED: frozenset(
        {TurnStatus.NARRATIVE_FAILED, TurnStatus.COMPLETED}
    ),
    TurnStatus.NARRATIVE_FAILED: frozenset(
        {TurnStatus.NARRATIVE_FAILED, TurnStatus.COMPLETED}
    ),
    TurnStatus.COMPLETED: frozenset(),
}


def require_turn_transition(before: TurnStatus, after: TurnStatus) -> None:
    if after not in _TURN_TRANSITIONS[before]:
        raise ValueError(f"invalid turn status transition: {before} -> {after}")


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    text: str
    idempotency_key: str | None = None
    request_id: str = ""
    debug: bool = False
    narrative_max_chars: int = Field(
        default=DEFAULT_NARRATIVE_CHARS,
        ge=MIN_NARRATIVE_CHARS,
        le=MAX_NARRATIVE_CHARS,
    )


class Choice(BaseModel):
    label: str
    hint: str = ""
    action_type: str = ""
    #: ``narrator`` when the option came out of the chapter that was just
    #: written, ``engine`` when it is a generic affordance derived from world
    #: state. The player-facing layer shows narrator options as written and
    #: never pads them out; it has no way to make an engine affordance as
    #: specific as a line the narrator wrote knowing who was mid-sentence.
    source: str = ""


class StoryBeat(BaseModel):
    """Where a scene hands control back to the player.

    A text RPG that asks "what do you do?" after every sentence is a command
    prompt wearing a novel's clothes. The narrator instead plays out whatever
    does not need a decision, and raises a beat when one genuinely does -
    someone asked a question, a blade came out, a door opened.
    """

    model_config = ConfigDict(extra="forbid")

    #: False means the scene can keep running on its own if the player says so.
    needs_player: bool = True
    #: In-fiction, e.g. "他等着你回话" - never "please enter a command".
    question: str = ""
    options: list[Choice] = Field(default_factory=list)


class TurnResult(BaseModel):
    """Exactly the shape Prompt section 50 specifies, plus turn_id and debug."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str
    idempotency_key: str = ""
    turn_number: int = 0
    status: TurnStatus = TurnStatus.COMPLETED
    narrative: str = ""
    state_changes: dict[str, Any] = Field(default_factory=dict)
    visible_updates: dict[str, Any] = Field(default_factory=dict)
    choices: list[Choice] = Field(default_factory=list)
    beat: StoryBeat | None = None
    #: Why the story stopped and handed control back (see InterruptReason).
    interrupt: dict[str, Any] | None = None
    #: How many adjudicated steps this chapter covers. 1 for a single turn.
    steps: int = 1
    rejected: dict[str, Any] | None = None
    degraded: bool = False
    debug: dict[str, Any] | None = None


@dataclass(slots=True)
class StageTimer:
    timings: dict[str, int] = field(default_factory=dict)
    _open: dict[str, float] = field(default_factory=dict)

    def start(self, stage: str) -> None:
        self._open[stage] = time.perf_counter()

    def stop(self, stage: str) -> None:
        started = self._open.pop(stage, None)
        if started is not None:
            self.timings[stage] = int((time.perf_counter() - started) * 1000)

    def measure(self, stage: str):
        timer = self

        class _Ctx:
            def __enter__(self) -> None:
                timer.start(stage)

            def __exit__(self, *exc: Any) -> None:
                timer.stop(stage)

        return _Ctx()


@dataclass(slots=True)
class TurnTrace:
    """Everything the debug panel needs to explain a turn."""

    turn_id: str
    request_id: str = ""
    session_id: str = ""
    world_id: str = ""
    stage_timings: dict[str, int] = field(default_factory=dict)
    intent: dict[str, Any] | None = None
    rule_result: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None
    npc_decisions: list[dict[str, Any]] = field(default_factory=list)
    director: dict[str, Any] | None = None
    simulation: dict[str, Any] | None = None
    proposals: dict[str, Any] = field(default_factory=dict)
    consistency: list[dict[str, Any]] = field(default_factory=list)
    state_changes: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    context_snapshots: dict[str, Any] = field(default_factory=dict)
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    rng_traces: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    narrative_style: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "world_id": self.world_id,
            "stage_timings": self.stage_timings,
            "intent": self.intent,
            "rule_result": self.rule_result,
            "outcome": self.outcome,
            "npc_decisions": self.npc_decisions,
            "director": self.director,
            "simulation": self.simulation,
            "proposals": self.proposals,
            "consistency": self.consistency,
            "state_changes": self.state_changes,
            "memory": self.memory,
            "context_snapshots": self.context_snapshots,
            "llm_calls": self.llm_calls,
            "rng_traces": self.rng_traces,
            "token_usage": self.token_usage,
            "errors": self.errors,
            "narrative_style": self.narrative_style,
        }


def record_llm_calls(records: list[LLMCallRecord]) -> list[dict[str, Any]]:
    return [r.model_dump() for r in records]


def record_rng(traces: list[RngTrace]) -> list[dict[str, Any]]:
    return [t.model_dump() for t in traces]


@dataclass(slots=True)
class OrchestratorPlan:
    """Which subsystems this turn actually needs (Prompt section 6)."""

    needs_intent_llm: bool = True
    needs_npcs: bool = True
    needs_director: bool = True
    needs_simulation: bool = True
    needs_narrative: bool = True
    needs_memory: bool = True
    reason: str = ""

    @classmethod
    def for_query(cls, reason: str = "query_action") -> OrchestratorPlan:
        return cls(
            needs_intent_llm=False,
            needs_npcs=False,
            needs_director=False,
            needs_simulation=False,
            needs_narrative=False,
            needs_memory=False,
            reason=reason,
        )

    @classmethod
    def for_rejection(cls) -> OrchestratorPlan:
        return cls(
            needs_npcs=False,
            needs_director=False,
            needs_simulation=False,
            needs_narrative=True,
            needs_memory=False,
            reason="rule_rejected",
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent_llm": self.needs_intent_llm,
            "npcs": self.needs_npcs,
            "director": self.needs_director,
            "simulation": self.needs_simulation,
            "narrative": self.needs_narrative,
            "memory": self.needs_memory,
            "reason": self.reason,
        }


def action_summary(
    intent: PlayerIntent, action: Action, rule_result: RuleResult, outcome: ActionOutcome
) -> dict[str, Any]:
    return {
        "intent": intent.model_dump(mode="json"),
        "action": action.model_dump(mode="json"),
        "rule_result": rule_result.model_dump(mode="json"),
        "outcome": outcome.model_dump(mode="json"),
    }

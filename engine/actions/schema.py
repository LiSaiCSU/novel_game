"""The Action protocol (Prompt section 7).

Natural language is not a game input. Actions are. Everything a player types is
converted into one of these before the world will look at it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from engine.core.types import ActionType, ReasonCode, RequestSize, SocialMethod


class ActionGoal(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = "other"
    topic: str | None = None
    item_key: str | None = None
    quantity: int | None = None
    details: str | None = None


class PredicateKind(StrEnum):
    PREVIOUS_SUCCEEDED = "PREVIOUS_SUCCEEDED"
    HAS_ITEM = "HAS_ITEM"
    TARGET_PRESENT = "TARGET_PRESENT"
    AT_LOCATION = "AT_LOCATION"


class ActionCondition(BaseModel):
    """A predicate Code can evaluate; free-form trigger prose is not executable."""

    model_config = ConfigDict(extra="forbid")

    kind: PredicateKind
    primitive_id: str | None = None
    item_key: str | None = None
    target_id: str | None = None
    location_key: str | None = None

    @model_validator(mode="after")
    def _required_operand(self) -> ActionCondition:
        required = {
            PredicateKind.PREVIOUS_SUCCEEDED: self.primitive_id,
            PredicateKind.HAS_ITEM: self.item_key,
            PredicateKind.TARGET_PRESENT: self.target_id,
            PredicateKind.AT_LOCATION: self.location_key,
        }
        if not required[self.kind]:
            raise ValueError(f"{self.kind} requires its matching operand")
        return self


class ActionPrimitiveIntent(BaseModel):
    """One fully structured step proposed by the intent model."""

    model_config = ConfigDict(extra="forbid")

    primitive_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)
    action_type: ActionType
    target_id: str | None = None
    target_key: str | None = None
    location_key: str | None = None
    item_key: str | None = None
    skill_key: str | None = None
    quest_key: str | None = None
    quantity: int = Field(default=1, ge=1)
    duration_minutes: int | None = Field(default=None, ge=0)
    method: SocialMethod | str | None = None
    style: str | None = None
    request_size: RequestSize = RequestSize.TRIVIAL
    goal: ActionGoal = Field(default_factory=ActionGoal)
    condition: ActionCondition | None = None
    utterance: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ActionPlanIntent(BaseModel):
    """A short, tightly coupled plan. Long temporal work remains separate turns."""

    model_config = ConfigDict(extra="forbid")

    atomic: Literal[True] = True
    primitives: list[ActionPrimitiveIntent] = Field(min_length=2, max_length=4)


class PlayerIntent(BaseModel):
    """The Intent Parser's only output. It decides nothing about outcomes."""

    model_config = ConfigDict(extra="forbid")

    action_type: ActionType = ActionType.CUSTOM
    actor_id: str = "player"
    target_id: str | None = None
    target_key: str | None = None
    location_key: str | None = None
    item_key: str | None = None
    skill_key: str | None = None
    quest_key: str | None = None
    quantity: int = 1
    duration_minutes: int | None = None
    method: SocialMethod | str | None = None
    style: str | None = None
    request_size: RequestSize = RequestSize.TRIVIAL
    goal: ActionGoal = Field(default_factory=ActionGoal)
    plan: ActionPlanIntent | None = None
    utterance: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    raw_text: str = ""
    confidence: float = 1.0
    ambiguity: str | None = None
    #: Names the player used that the world does not have yet. These are the
    #: steward's work list, not a reason to reject the turn.
    unresolved_reference: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("unresolved_reference", mode="before")
    @classmethod
    def _one_or_many(cls, value: Any) -> Any:
        """Models reach for a bare string here often enough to just accept it."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @field_validator("quantity")
    @classmethod
    def _positive_quantity(cls, value: int) -> int:
        return max(1, int(value))

    def needs_clarification(self, threshold: float = 0.3) -> bool:
        """Only truly unreadable input. Anything legible is the world's problem.

        This used to trip on any unbound reference, which turned every creative
        line into a wasted turn. Unbound references now route to the steward
        instead; the bar here is 'we cannot tell what was even attempted'.
        """
        return self.confidence < threshold


class Action(BaseModel):
    """A resolved, engine-facing action: ids filled in, targets verified."""

    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    actor_id: str
    target_id: str | None = None
    target_location_id: str | None = None
    item_key: str | None = None
    skill_key: str | None = None
    quest_id: str | None = None
    quantity: int = 1
    duration_minutes: int | None = None
    method: str | None = None
    style: str | None = None
    request_size: RequestSize = RequestSize.TRIVIAL
    goal: ActionGoal = Field(default_factory=ActionGoal)
    utterance: str | None = None
    raw_text: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    def is_social(self) -> bool:
        from engine.core.types import SOCIAL_ACTIONS

        return self.action_type in SOCIAL_ACTIONS


class ActionPrimitive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primitive_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)
    action: Action
    condition: ActionCondition | None = None


class ActionPlan(BaseModel):
    """Engine-facing atomic proposal compiled from one player utterance."""

    model_config = ConfigDict(extra="forbid")

    atomic: Literal[True] = True
    primitives: list[ActionPrimitive] = Field(min_length=1, max_length=4)


class RuleResult(BaseModel):
    """The deterministic verdict. No LLM may overturn it (Prompt section 8)."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason_code: ReasonCode = ReasonCode.OK
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(cls, **details: Any) -> RuleResult:
        return cls(allowed=True, reason_code=ReasonCode.OK, details=details)

    @classmethod
    def deny(cls, reason_code: ReasonCode, reason: str = "", **details: Any) -> RuleResult:
        return cls(allowed=False, reason_code=reason_code, reason=reason, details=details)


class ActionOutcome(BaseModel):
    """What actually happened, after rules and RNG. Facts, not prose."""

    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    success: bool = True
    summary_key: str = ""
    time_cost_minutes: int = 0
    facts: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    detected: bool = False
    importance: float = 0.1

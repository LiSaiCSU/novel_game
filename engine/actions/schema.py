"""The Action protocol (Prompt section 7).

Natural language is not a game input. Actions are. Everything a player types is
converted into one of these before the world will look at it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from engine.core.types import ActionType, ReasonCode, RequestSize, SocialMethod


class ActionGoal(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = "other"
    topic: str | None = None
    item_key: str | None = None
    quantity: int | None = None
    details: str | None = None


class SecondaryAction(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    target_id: str | None = None
    details: str | None = None


class ActionCondition(BaseModel):
    """Supports "if the guard turns away, I climb through the window"."""

    model_config = ConfigDict(extra="allow")

    trigger: str
    then_action_type: ActionType | None = None
    then_target_id: str | None = None


class PlayerIntent(BaseModel):
    """The Intent Parser's only output. It decides nothing about outcomes."""

    model_config = ConfigDict(extra="ignore")

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
    secondary_actions: list[SecondaryAction] = Field(default_factory=list)
    condition: ActionCondition | None = None
    utterance: str | None = None
    raw_text: str = ""
    confidence: float = 1.0
    ambiguity: str | None = None

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @field_validator("quantity")
    @classmethod
    def _positive_quantity(cls, value: int) -> int:
        return max(1, int(value))

    def needs_clarification(self, threshold: float = 0.45) -> bool:
        return self.ambiguity is not None or self.confidence < threshold


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
    secondary_actions: list[SecondaryAction] = Field(default_factory=list)
    condition: ActionCondition | None = None
    utterance: str | None = None
    raw_text: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    def is_social(self) -> bool:
        from engine.core.types import SOCIAL_ACTIONS

        return self.action_type in SOCIAL_ACTIONS


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

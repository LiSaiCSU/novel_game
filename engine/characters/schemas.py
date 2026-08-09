"""Structured outputs proposed by AI subsystems.

Every one of these is a *proposal*. The validators in
``engine/orchestrator/proposals.py`` decide what, if anything, reaches the
world (Prompt section 18).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from engine.core.types import DirectorDecisionType, MemoryTag, Urgency


class EmotionUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dominant: str | None = None
    valence: float | None = None
    arousal: float | None = None
    intensity: float | None = None


class NPCDecisionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action_type: str = "WAIT"
    target: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class NPCDecision(BaseModel):
    """Prompt section 19."""

    model_config = ConfigDict(extra="ignore")

    reasoning_summary: str = ""
    decision: NPCDecisionBody = Field(default_factory=NPCDecisionBody)
    speech_intent: str = ""
    spoken_line: str | None = None
    emotion_update: EmotionUpdate = Field(default_factory=EmotionUpdate)
    relationship_change_proposal: dict[str, dict[str, float]] = Field(default_factory=dict)
    goal_update_proposal: dict[str, Any] | None = None
    refuses: bool = False

    @field_validator("relationship_change_proposal", mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return {}
        out: dict[str, dict[str, float]] = {}
        for who, deltas in value.items():
            if isinstance(deltas, dict):
                out[str(who)] = {
                    str(k): float(v) for k, v in deltas.items() if isinstance(v, (int, float))
                }
        return out


class DirectorDecision(BaseModel):
    """Prompt section 24."""

    model_config = ConfigDict(extra="ignore")

    decision: DirectorDecisionType = DirectorDecisionType.NO_EVENT
    source_plot_thread: str | None = None
    event_type: str | None = None
    participants: list[str] = Field(default_factory=list)
    proposal: str = ""
    causal_basis: list[str] = Field(default_factory=list)
    narrative_purpose: list[str] = Field(default_factory=list)
    urgency: Urgency = Urgency.LOW
    tension_delta: float = 0.0

    @field_validator("tension_delta")
    @classmethod
    def _clamp_tension(cls, value: float) -> float:
        return max(-30.0, min(30.0, float(value)))


class FactLearned(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fact_key: str
    state: str = "BELIEVED"
    confidence: float = 0.6


class MemoryExtraction(BaseModel):
    """Prompt section 28."""

    model_config = ConfigDict(extra="ignore")

    should_store: bool = False
    importance: float = 0.0
    memory_type: MemoryTag = MemoryTag.OTHER
    summary: str = ""
    characters: list[str] = Field(default_factory=list)
    facts_learned: list[FactLearned] = Field(default_factory=list)
    relationship_implications: dict[str, dict[str, float]] = Field(default_factory=dict)
    emotional_valence: float = 0.0

    @field_validator("importance", "emotional_valence")
    @classmethod
    def _clamp(cls, value: float) -> float:
        return max(-1.0, min(1.0, float(value)))

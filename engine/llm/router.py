"""ModelRouter (Prompt section 48).

Cheap models for parsing and bookkeeping, strong models for the characters and
decisions the player will actually notice. Every name comes from .env.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from engine.core.types import CharacterType, LLMRole


@dataclass(frozen=True, slots=True)
class ModelChoice:
    role: LLMRole
    model: str
    temperature: float
    max_output_tokens: int

    @property
    def configured(self) -> bool:
        return bool(self.model)


class ModelRouter:
    _DEFAULT_TEMPERATURE: ClassVar[dict[LLMRole, float]] = {
        LLMRole.INTENT: 0.2,
        LLMRole.NPC: 0.7,
        LLMRole.NPC_MAJOR: 0.7,
        LLMRole.DIRECTOR: 0.6,
        LLMRole.NARRATIVE: 0.85,
        LLMRole.MEMORY: 0.3,
        LLMRole.EMBEDDING: 0.0,
    }
    _DEFAULT_MAX_TOKENS: ClassVar[dict[LLMRole, int]] = {
        LLMRole.INTENT: 1200,
        LLMRole.NPC: 1200,
        LLMRole.NPC_MAJOR: 1600,
        LLMRole.DIRECTOR: 1200,
        LLMRole.STEWARD: 1600,
        # A scene, not a status line. This is the single biggest lever on how
        # the game reads, so it gets room to actually write one.
        LLMRole.NARRATIVE: 2600,
        LLMRole.MEMORY: 800,
        LLMRole.EMBEDDING: 8,
    }

    def __init__(self, settings: Any) -> None:
        self._budget_scale = max(
            0.25, float(getattr(settings, "llm_output_budget_scale", 1.0) or 1.0)
        )
        default_model = getattr(settings, "llm_model", "") or ""
        self._models: dict[LLMRole, str] = {
            LLMRole.INTENT: getattr(settings, "intent_model", "") or default_model,
            LLMRole.NPC: getattr(settings, "npc_model", "") or default_model,
            LLMRole.NPC_MAJOR: getattr(settings, "npc_major_model", "") or default_model,
            LLMRole.DIRECTOR: getattr(settings, "director_model", "") or default_model,
            LLMRole.STEWARD: getattr(settings, "steward_model", "") or default_model,
            LLMRole.NARRATIVE: getattr(settings, "narrative_model", "") or default_model,
            LLMRole.MEMORY: getattr(settings, "memory_model", "") or default_model,
            LLMRole.EMBEDDING: getattr(settings, "embedding_model", "") or "",
        }
        # A major-NPC model is optional; fall back to the ordinary NPC model.
        if not self._models[LLMRole.NPC_MAJOR]:
            self._models[LLMRole.NPC_MAJOR] = self._models[LLMRole.NPC]
        # The steward is new; existing deployments should get it for free.
        if not self._models[LLMRole.STEWARD]:
            self._models[LLMRole.STEWARD] = self._models[LLMRole.INTENT]

    def choose(
        self, role: LLMRole, *, temperature: float | None = None, max_output_tokens: int | None = None
    ) -> ModelChoice:
        return ModelChoice(
            role=role,
            model=self._models.get(role, ""),
            temperature=(
                self._DEFAULT_TEMPERATURE.get(role, 0.7) if temperature is None else temperature
            ),
            max_output_tokens=(
                int(self._DEFAULT_MAX_TOKENS.get(role, 800) * self._budget_scale)
                if max_output_tokens is None
                else max_output_tokens
            ),
        )

    def for_npc(self, character_type: CharacterType) -> ModelChoice:
        """Important characters deserve the stronger model."""
        role = LLMRole.NPC_MAJOR if character_type is CharacterType.MAJOR_NPC else LLMRole.NPC
        return self.choose(role)

    def configured_roles(self) -> list[LLMRole]:
        return [role for role, model in self._models.items() if model]

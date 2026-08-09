"""NPCAgent - a decision system, not a chatbot (Prompt section 19).

Two implementations behind one interface:

* the LLM path, given only what this character knows;
* a deterministic heuristic that applies the same personality, relationship and
  knowledge constraints in arithmetic.

The heuristic is not a stub. It is what makes the three behavioural evals
(refuse an absurd request, do not confess to a secret you were never told, do
not help a stranger because they are the protagonist) hold even with no model
configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.characters.schemas import EmotionUpdate, NPCDecision, NPCDecisionBody
from engine.contentpack.pack import ContentPack
from engine.context.builder import BuiltContext, ContextBuilder
from engine.core.errors import LLMError, StructuredOutputError
from engine.core.logging import get_logger
from engine.core.models import Character, Fact
from engine.core.ports import UnitOfWork
from engine.core.types import (
    ActionType,
    KnowledgeState,
    LLMRole,
    ReasonCode,
    RequestSize,
)
from engine.knowledge.service import KnowledgeService
from engine.rules.base import RuleContext
from engine.rules.combat import CombatRules
from engine.rules.interaction import InteractionRules

logger = get_logger("npc")

#: Response shapes the heuristic can produce. Kept as keys so the wording stays
#: in the content pack's narrative templates.
SPEECH_DENY_UNKNOWN = "deny_unknown"
SPEECH_REFUSE = "refuse"
SPEECH_COMPLY = "comply"
SPEECH_DEFLECT = "deflect"
SPEECH_NEUTRAL = "neutral"


@dataclass(slots=True)
class NPCSituation:
    """Everything the agent needs to know about what just happened to it."""

    player_action: ActionType
    is_target: bool = False
    utterance: str | None = None
    method: str | None = None
    request_size: RequestSize = RequestSize.TRIVIAL
    topic: str | None = None
    referenced_facts: list[tuple[Fact, float]] = field(default_factory=list)
    summary: str = ""


@dataclass(slots=True)
class NPCDecisionResult:
    npc_id: str
    npc_key: str
    decision: NPCDecision
    degraded: bool
    context: BuiltContext | None = None
    reasons: list[str] = field(default_factory=list)


class NPCAgent:
    def __init__(
        self,
        pack: ContentPack,
        knowledge: KnowledgeService,
        context_builder: ContextBuilder,
        llm: Any | None = None,
        registry: Any | None = None,
        prompt_version: str = "v1",
    ) -> None:
        self.pack = pack
        self.knowledge = knowledge
        self.context_builder = context_builder
        self.llm = llm
        self.registry = registry
        self.prompt_version = prompt_version

    # ------------------------------------------------------------------
    async def decide(
        self,
        uow: UnitOfWork,
        ctx: RuleContext,
        npc: Character,
        situation: NPCSituation,
        available_actions: list[str],
    ) -> NPCDecisionResult:
        state = ctx.state
        context = await self.context_builder.build_npc_context(
            uow,
            state,
            npc,
            situation=situation.summary,
            query=situation.utterance or situation.summary,
            available_actions=available_actions,
        )

        if self.llm is not None and self.registry is not None and self.llm.usable_for(
            self._role(npc)
        ):
            try:
                decision = await self._decide_with_llm(npc, context)
                return NPCDecisionResult(
                    npc_id=npc.id,
                    npc_key=npc.key,
                    decision=decision,
                    degraded=False,
                    context=context,
                )
            except (LLMError, StructuredOutputError) as exc:
                logger.warning("npc decision fell back to heuristics for %s: %s", npc.key, exc)
                if self.llm is not None:
                    self.llm.record_degraded(self._role(npc), str(exc))

        decision, reasons = await self._decide_heuristically(uow, ctx, npc, situation, available_actions)
        return NPCDecisionResult(
            npc_id=npc.id,
            npc_key=npc.key,
            decision=decision,
            degraded=True,
            context=context,
            reasons=reasons,
        )

    def _role(self, npc: Character) -> LLMRole:
        from engine.core.types import CharacterType

        return LLMRole.NPC_MAJOR if npc.character_type is CharacterType.MAJOR_NPC else LLMRole.NPC

    # ------------------------------------------------------------------
    async def _decide_with_llm(self, npc: Character, context: BuiltContext) -> NPCDecision:
        assert self.llm is not None and self.registry is not None  # guarded by decide()
        prompt = self.registry.render(
            "npc_decision",
            self.prompt_version,
            schema=self.llm.schema_hint(NPCDecision),
            **context.sections,
        )
        return await self.llm.generate_structured(
            self._role(npc),
            NPCDecision,
            prompt,
            prompt_version=self.prompt_version,
        )

    # ------------------------------------------------------------------
    async def _decide_heuristically(
        self,
        uow: UnitOfWork,
        ctx: RuleContext,
        npc: Character,
        situation: NPCSituation,
        available_actions: list[str],
    ) -> tuple[NPCDecision, list[str]]:
        state = ctx.state
        player = state.player
        reasons: list[str] = []
        relationship = await uow.relationships.get(npc.id, player.id)

        # --- being attacked overrides everything --------------------------
        if situation.player_action is ActionType.ATTACK and situation.is_target:
            return self._react_to_violence(ctx, npc, available_actions, reasons), reasons

        # --- asked about something this character does not know ------------
        unknown_topic = await self._first_unknown_reference(uow, npc, situation)
        if unknown_topic is not None:
            reasons.append(f"asked_about_unknown_fact:{unknown_topic.key}")
            suspicion = 4 if unknown_topic.sensitivity >= 0.6 else 1
            return (
                NPCDecision(
                    reasoning_summary=(
                        "This character has never learned the thing being asserted and "
                        "cannot confirm it."
                    ),
                    decision=NPCDecisionBody(action_type=str(ActionType.TALK), target=player.key),
                    speech_intent=SPEECH_DENY_UNKNOWN,
                    emotion_update=EmotionUpdate(dominant="wary", intensity=0.4),
                    relationship_change_proposal={player.key: {"suspicion": suspicion}},
                    refuses=True,
                ),
                reasons,
            )

        # --- a request that must be weighed --------------------------------
        if situation.request_size is not RequestSize.TRIVIAL or situation.method in (
            "persuade",
            "bribe",
            "intimidate",
            "threaten",
            "promise",
            "negotiate",
        ):
            violates_values, violates_taboo = InteractionRules.request_conflicts(
                npc, situation.topic or "", situation.utterance
            )
            odds = InteractionRules.calculate_probability(
                ctx,
                player,
                npc,
                relationship,
                request_size=situation.request_size,
                risk_to_target=_risk_for(situation.request_size),
                violates_values=violates_values,
                violates_taboo=violates_taboo,
                method=situation.method,
                actor_reputation=player.reputation.global_,
            )
            reasons.append(f"social_odds={odds.chance:.3f}")
            reasons += odds.reasons
            complied = (not odds.hard_refusal) and ctx.rng.chance(odds.chance)
            if not complied:
                deltas: dict[str, float] = {}
                if situation.method in ("intimidate", "threaten"):
                    deltas = {"fear": 2, "hatred": 2, "trust": -2}
                elif situation.request_size in (RequestSize.LARGE, RequestSize.EXTREME):
                    deltas = {"suspicion": 2}
                return (
                    NPCDecision(
                        reasoning_summary="The request is too large for this relationship.",
                        decision=NPCDecisionBody(
                            action_type=str(ActionType.TALK), target=player.key
                        ),
                        speech_intent=SPEECH_REFUSE,
                        emotion_update=EmotionUpdate(dominant="guarded", intensity=0.35),
                        relationship_change_proposal={player.key: deltas} if deltas else {},
                        refuses=True,
                    ),
                    reasons,
                )
            return (
                NPCDecision(
                    reasoning_summary="The relationship and the size of the ask make this acceptable.",
                    decision=NPCDecisionBody(action_type=str(ActionType.TALK), target=player.key),
                    speech_intent=SPEECH_COMPLY,
                    emotion_update=EmotionUpdate(dominant="obliging", intensity=0.3),
                    relationship_change_proposal={player.key: {"familiarity": 1}},
                ),
                reasons,
            )

        # --- ordinary conversation ----------------------------------------
        if situation.is_target and situation.player_action in (
            ActionType.TALK,
            ActionType.ASK,
            ActionType.CONVERSATION,
        ):
            guarded = npc.personality.trait("cautious", 0.5) > 0.7 and (
                relationship is None or relationship.trust < 20
            )
            reasons.append("small_talk")
            return (
                NPCDecision(
                    reasoning_summary="Nothing here demands more than a civil answer.",
                    decision=NPCDecisionBody(action_type=str(ActionType.TALK), target=player.key),
                    speech_intent=SPEECH_DEFLECT if guarded else SPEECH_NEUTRAL,
                    emotion_update=EmotionUpdate(intensity=0.2),
                    relationship_change_proposal={player.key: {"familiarity": 1}},
                ),
                reasons,
            )

        # --- not involved: keep living your own life -----------------------
        reasons.append("not_involved")
        return (
            NPCDecision(
                reasoning_summary="This character has business of their own.",
                decision=NPCDecisionBody(action_type=str(ActionType.WAIT)),
                speech_intent="",
            ),
            reasons,
        )

    # ------------------------------------------------------------------
    async def _first_unknown_reference(
        self, uow: UnitOfWork, npc: Character, situation: NPCSituation
    ) -> Fact | None:
        """The heart of Eval 2.

        If the player asserts or asks about a fact this character has never
        learned, the character does not suddenly know it - no matter how
        confidently it was said.
        """
        if not situation.referenced_facts:
            return None
        for fact, _score in situation.referenced_facts:
            row = await uow.knowledge.get_knowledge(npc.id, fact.id)
            state = row.knowledge_state if row else KnowledgeState.UNKNOWN
            if state in (KnowledgeState.UNKNOWN, KnowledgeState.DISBELIEVED):
                return fact
        return None

    def _react_to_violence(
        self, ctx: RuleContext, npc: Character, available_actions: list[str], reasons: list[str]
    ) -> NPCDecision:
        player = ctx.state.player
        flee_chance = CombatRules.calculate_flee_chance(ctx, npc, player)
        wants_to_flee = (
            npc.personality.risk_tolerance < 0.4
            or npc.health < npc.max_health * 0.35
            or ctx.pack.realms.realm_gap(player.realm, npc.realm) >= 1
        )
        reasons.append(f"under_attack flee_chance={flee_chance:.2f}")
        if wants_to_flee and str(ActionType.MOVE) in available_actions:
            return NPCDecision(
                reasoning_summary="Outmatched. Survival first.",
                decision=NPCDecisionBody(action_type=str(ActionType.MOVE)),
                speech_intent=SPEECH_REFUSE,
                emotion_update=EmotionUpdate(dominant="afraid", intensity=0.85, valence=-0.7),
                relationship_change_proposal={player.key: {"fear": 12, "hatred": 8, "trust": -10}},
            )
        action = (
            str(ActionType.ATTACK)
            if str(ActionType.ATTACK) in available_actions
            else str(ActionType.DEFEND)
        )
        return NPCDecision(
            reasoning_summary="Attacked without cause. Fight back.",
            decision=NPCDecisionBody(action_type=action, target=player.key),
            speech_intent=SPEECH_REFUSE,
            emotion_update=EmotionUpdate(dominant="furious", intensity=0.9, valence=-0.8),
            relationship_change_proposal={player.key: {"hatred": 15, "trust": -12, "fear": 4}},
        )


def _risk_for(size: RequestSize) -> float:
    return {
        RequestSize.TRIVIAL: 0.0,
        RequestSize.SMALL: 0.1,
        RequestSize.MODERATE: 0.3,
        RequestSize.LARGE: 0.55,
        RequestSize.EXTREME: 0.85,
    }.get(size, 0.0)


def rejection_reason_code(decision: NPCDecision) -> ReasonCode:
    return ReasonCode.OK if not decision.refuses else ReasonCode.NOT_PHYSICALLY_POSSIBLE

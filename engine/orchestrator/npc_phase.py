"""NPC decision phase for a single canonical turn.

Keeping this phase separate makes its model-call budget and proposal boundary
testable without involving the transaction coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.actions.schema import Action, ActionOutcome
from engine.characters.npc_agent import (
    SPEECH_DEFLECT,
    SPEECH_DENY_UNKNOWN,
    SPEECH_REFUSE,
    NPCAgent,
    NPCDecisionResult,
    NPCSituation,
)
from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.models import Character, Fact
from engine.core.mutations import ChangeSet
from engine.core.ports import UnitOfWork
from engine.core.types import CharacterType, KnowledgeState
from engine.knowledge.service import _STRENGTH, KnowledgeService
from engine.narrative.renderer import NarrativeRenderer
from engine.orchestrator.proposals import ProposalValidator
from engine.orchestrator.turn import TurnTrace
from engine.rules.base import RuleContext
from engine.rules.engine import RuleEngine
from engine.world.state_view import WorldStateView

#: Speech intents that mean the answer was withheld, so nothing reached
#: the player and nothing should be written down as learned.
WITHHOLDING_INTENTS: frozenset[str] = frozenset(
    {SPEECH_REFUSE, SPEECH_DEFLECT, SPEECH_DENY_UNKNOWN}
)


@dataclass(slots=True)
class NpcPhase:
    pack: ContentPack
    rules: RuleEngine
    knowledge: KnowledgeService
    agent: NPCAgent
    proposals: ProposalValidator
    narrative: NarrativeRenderer


    async def run(
        self,
        uow: UnitOfWork,
        ctx: RuleContext,
        action: Action,
        outcome: ActionOutcome,
        change_set: ChangeSet,
        trace: TurnTrace,
    ) -> list[str]:
        """Decide present NPC reactions and accept only validated proposals."""
        state = ctx.state
        dying = {
            change.target_id
            for change in change_set.by_kind(mut.ChangeKind.CHARACTER_DEATH)
        }
        present = [
            character
            for character in state.present_characters
            if character.alive and character.id not in dying
        ]
        if not present:
            return []

        referenced = await self.knowledge.match_facts(
            uow, state.world.id, action.utterance or action.raw_text
        )
        llm_budget = int(self.pack.rule("auto_advance.npc_llm_per_step", 2))
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
            available = self.rules.available_actions(ctx, npc.id)
            result = await self.agent.decide(
                uow,
                ctx,
                npc,
                situation,
                available,
                allow_llm=self.deserves_model(npc, action, llm_budget),
            )
            if not result.degraded:
                llm_budget -= 1
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
                    "context_tokens": (
                        result.context.estimated_tokens if result.context else 0
                    ),
                }
            )
            if result.context is not None:
                trace.context_snapshots[f"npc:{npc.key}"] = result.context.as_dict()

            disclosed = await self._disclose(
                uow, state, action, npc, result, referenced, change_set
            )
            if disclosed:
                trace.npc_decisions[-1]["disclosed_facts"] = disclosed

            # A character who says nothing may still have done something, and
            # the narrator can only write about what it is told. Two thirds of
            # the people in a scene used to report nothing at all.
            line = self.narrative.npc_line(
                npc,
                result.decision.speech_intent,
                result.decision.spoken_line,
                str(result.decision.decision.action_type or ""),
            )
            if line:
                lines.append(line)
        return lines

    # ------------------------------------------------------------------
    async def _disclose(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        action: Action,
        npc: Character,
        result: NPCDecisionResult,
        referenced: list[tuple[Fact, float]],
        change_set: ChangeSet,
    ) -> list[str]:
        """Write down what the player just got told.

        Belief was seeded once at world creation and then never moved: asking
        the one person who knows where the array eye is, and being answered,
        left the player's knowledge exactly as it had been - so every later
        prompt still described them as not knowing. An answer that was
        actually given is evidence, and this is where it becomes state.

        Deliberately narrow. Only the person being spoken to, only facts the
        player themselves raised, only when that person both knows the answer
        and did not refuse to give it.
        """
        if not referenced or action.target_id != npc.id or result.decision.refuses:
            return []
        if not (result.decision.speech_intent or result.decision.spoken_line):
            return []
        if result.decision.speech_intent in WITHHOLDING_INTENTS:
            return []

        credibility = float(self.pack.rule("information.teller_credibility", 0.8))
        learned: list[str] = []
        for fact, _score in referenced:
            known = await uow.knowledge.get_knowledge(npc.id, fact.id)
            if known is None or _STRENGTH[known.knowledge_state] < _STRENGTH[KnowledgeState.BELIEVED]:
                continue
            already = await uow.knowledge.get_knowledge(state.player.id, fact.id)
            if already is not None and _STRENGTH[already.knowledge_state] >= _STRENGTH[
                KnowledgeState.BELIEVED
            ]:
                continue
            change_set.add(
                self.knowledge.told(
                    state.player.id,
                    fact,
                    teller_id=npc.id,
                    teller_credibility=credibility * max(0.25, known.confidence),
                    at_minute=state.world.current_minute,
                )
            )
            learned.append(fact.key)
        return learned

    @staticmethod
    def deserves_model(npc: Character, action: Action, remaining_budget: int) -> bool:
        """Reserve model calls for the target and budgeted major characters."""
        if action.target_id == npc.id:
            return True
        if remaining_budget <= 0:
            return False
        return npc.character_type is CharacterType.MAJOR_NPC

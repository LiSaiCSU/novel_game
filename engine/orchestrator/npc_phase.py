"""NPC decision phase for a single canonical turn.

Keeping this phase separate makes its model-call budget and proposal boundary
testable without involving the transaction coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.actions.schema import Action, ActionOutcome
from engine.characters.npc_agent import NPCAgent, NPCSituation
from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.models import Character
from engine.core.mutations import ChangeSet
from engine.core.ports import UnitOfWork
from engine.core.types import CharacterType
from engine.knowledge.service import KnowledgeService
from engine.narrative.renderer import NarrativeRenderer
from engine.orchestrator.proposals import ProposalValidator
from engine.orchestrator.turn import TurnTrace
from engine.rules.base import RuleContext
from engine.rules.engine import RuleEngine


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

            if result.decision.speech_intent or result.decision.spoken_line:
                line = self.narrative.npc_line(
                    npc,
                    result.decision.speech_intent,
                    result.decision.spoken_line,
                )
                if line:
                    lines.append(line)
        return lines

    @staticmethod
    def deserves_model(npc: Character, action: Action, remaining_budget: int) -> bool:
        """Reserve model calls for the target and budgeted major characters."""
        if action.target_id == npc.id:
            return True
        if remaining_budget <= 0:
            return False
        return npc.character_type is CharacterType.MAJOR_NPC

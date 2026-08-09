"""IntentParser (Prompt section 21).

Natural language in, structured Action out. Nothing else: it does not decide
outcomes, does not touch the world, and does not speak for NPCs.

The model's output is then *resolved* against the real scene - every id it
names must exist and be present, or the reference is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.actions.fallback_parser import FallbackIntentParser
from engine.actions.schema import Action, PlayerIntent
from engine.contentpack.pack import ContentPack
from engine.context.builder import ContextBuilder
from engine.core.errors import LLMError, StructuredOutputError
from engine.core.logging import get_logger
from engine.core.ports import UnitOfWork
from engine.core.types import QUERY_ACTIONS, ActionType, LLMRole
from engine.world.state_view import WorldStateView

logger = get_logger("intent")


@dataclass(slots=True)
class ParsedIntent:
    intent: PlayerIntent
    action: Action
    degraded: bool
    resolution_notes: list[str] = field(default_factory=list)


class IntentParser:
    def __init__(
        self,
        pack: ContentPack,
        context_builder: ContextBuilder,
        llm=None,
        registry=None,
        prompt_version: str = "v1",
    ) -> None:
        self.pack = pack
        self.context_builder = context_builder
        self.llm = llm
        self.registry = registry
        self.prompt_version = prompt_version
        self.fallback = FallbackIntentParser(pack)

    # ------------------------------------------------------------------
    async def parse(
        self, uow: UnitOfWork, state: WorldStateView, text: str, *, recent_narrative: str = ""
    ) -> ParsedIntent:
        intent: PlayerIntent | None = None
        degraded = True

        if self.llm is not None and self.registry is not None and self.llm.usable_for(
            LLMRole.INTENT
        ):
            try:
                context = await self.context_builder.build_intent_context(
                    uow, state, recent_narrative=recent_narrative
                )
                prompt = self.registry.render(
                    "player_intent",
                    self.prompt_version,
                    schema=self.llm.schema_hint(PlayerIntent),
                    action_types=", ".join(str(a) for a in ActionType),
                    player_input=text,
                    **context.sections,
                )
                intent = await self.llm.generate_structured(
                    LLMRole.INTENT, PlayerIntent, prompt, prompt_version=self.prompt_version
                )
                intent.raw_text = text
                degraded = False
            except (LLMError, StructuredOutputError) as exc:
                logger.warning("intent parsing fell back to keywords: %s", exc)
                self.llm.record_degraded(LLMRole.INTENT, str(exc))

        if intent is None:
            intent = self.fallback.parse(text, state)

        action, notes = self.resolve(state, intent)
        return ParsedIntent(
            intent=intent, action=action, degraded=degraded, resolution_notes=notes
        )

    # ------------------------------------------------------------------
    def resolve(self, state: WorldStateView, intent: PlayerIntent) -> tuple[Action, list[str]]:
        """Bind an intent to real entities. Unresolvable references are dropped."""
        notes: list[str] = []

        target_id: str | None = None
        if intent.target_id:
            if state.is_present(intent.target_id):
                target_id = intent.target_id
            else:
                notes.append(f"target_id_not_present:{intent.target_id}")
        if target_id is None and intent.target_key:
            character = state.character_by_key(intent.target_key)
            if character is not None:
                target_id = character.id
            else:
                notes.append(f"target_key_not_present:{intent.target_key}")

        target_location_id: str | None = None
        if intent.location_key:
            location = state.graph.by_key(intent.location_key)
            if location is not None:
                target_location_id = location.id
            else:
                notes.append(f"unknown_location:{intent.location_key}")

        item_key = intent.item_key
        if item_key and self.pack.item(item_key) is None:
            notes.append(f"unknown_item:{item_key}")
            item_key = None

        skill_key = intent.skill_key
        if skill_key and self.pack.skill(skill_key) is None:
            notes.append(f"unknown_skill:{skill_key}")
            skill_key = None

        quest_id: str | None = None
        if intent.quest_key:
            quest = next((q for q in state.active_quests if q.key == intent.quest_key), None)
            if quest is not None:
                quest_id = quest.id
            else:
                notes.append(f"unknown_quest:{intent.quest_key}")

        action_type = intent.action_type
        if action_type is ActionType.MOVE and target_location_id is None:
            action_type = ActionType.CUSTOM
            notes.append("move_without_destination")

        action = Action(
            action_type=action_type,
            actor_id=state.player.id,
            target_id=target_id,
            target_location_id=target_location_id,
            item_key=item_key,
            skill_key=skill_key,
            quest_id=quest_id,
            quantity=intent.quantity,
            duration_minutes=intent.duration_minutes,
            method=str(intent.method) if intent.method else None,
            style=intent.style,
            request_size=intent.request_size,
            goal=intent.goal,
            secondary_actions=intent.secondary_actions,
            condition=intent.condition,
            utterance=intent.utterance or (intent.raw_text if _is_social(action_type) else None),
            raw_text=intent.raw_text,
        )
        return action, notes

    # ------------------------------------------------------------------
    @staticmethod
    def is_query(action: Action) -> bool:
        return action.action_type in QUERY_ACTIONS


def _is_social(action_type: ActionType) -> bool:
    return action_type in (ActionType.TALK, ActionType.ASK, ActionType.CONVERSATION)

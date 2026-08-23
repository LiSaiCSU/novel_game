"""IntentParser (Prompt section 21).

Natural language in, structured Action out. Nothing else: it does not decide
outcomes, does not touch the world, and does not speak for NPCs.

The model's output is then *resolved* against the real scene - every id it
names must exist and be present, or the reference is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.actions.fallback_parser import FallbackIntentParser
from engine.actions.schema import (
    Action,
    ActionPlan,
    ActionPrimitive,
    ActionPrimitiveIntent,
    PlayerIntent,
)
from engine.contentpack.pack import ContentPack
from engine.context.builder import ContextBuilder
from engine.core.errors import LLMError, StructuredOutputError
from engine.core.logging import get_logger
from engine.core.ports import UnitOfWork
from engine.core.types import QUERY_ACTIONS, ActionType, LLMRole
from engine.world.state_view import WorldStateView

logger = get_logger("intent")


#: Resolution notes that mean "the world is missing something", as opposed to
#: notes about a malformed plan. Only these summon the steward.
_MISSING_ENTITY_PREFIXES = (
    "target_id_not_present:",
    "target_key_not_present:",
    "unknown_location:",
    "unknown_item:",
    "move_without_destination",
)

_WORLD_GROWTH_ACTIONS = frozenset(
    {
        ActionType.MOVE,
        ActionType.TALK,
        ActionType.ASK,
        ActionType.CONVERSATION,
        ActionType.FOLLOW,
        ActionType.ATTACK,
        ActionType.GIVE_ITEM,
        ActionType.STEAL,
        ActionType.BUY,
        ActionType.SELL,
    }
)


@dataclass(slots=True)
class ParsedIntent:
    intent: PlayerIntent
    action: Action
    plan: ActionPlan
    degraded: bool
    resolution_notes: list[str] = field(default_factory=list)
    #: What the player asked for that this turn could only start. Set when a
    #: social or hostile move had to become travel first; the orchestrator
    #: replays it as the next step of the same run.
    deferred_intent: PlayerIntent | None = None

    @property
    def unresolved(self) -> list[str]:
        """Everything the player named that the world could not supply."""
        out = list(self.intent.unresolved_reference)
        for note in self.resolution_notes:
            if note.startswith(_MISSING_ENTITY_PREFIXES):
                _, _, value = note.partition(":")
                out.append(value or note)
        # de-duplicate while keeping the order the player said them in
        seen: set[str] = set()
        unique: list[str] = []
        for phrase in out:
            if phrase and phrase not in seen:
                seen.add(phrase)
                unique.append(phrase)
        return unique

    @property
    def needs_steward(self) -> bool:
        if any(note.startswith(_MISSING_ENTITY_PREFIXES) for note in self.resolution_notes):
            return True
        if not self.intent.unresolved_reference:
            return False
        # A free-form observation can mention letters, weather, clothing, or
        # any other narrative prop. Those words are context for the narrator,
        # not a request to spend a model call inventing a new world entity.
        return self.intent.action_type in _WORLD_GROWTH_ACTIONS or self.intent.ambiguity in {
            "move_target_unknown",
            "conversation_target_unknown",
        }


#: Actions that are *about* a person and therefore survive the trip to reach
#: them. A bare MOVE has nothing left over once the walk is done, so turning
#: one into travel plus a replay would invent a second action nobody asked for.
DEFERRABLE_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.TALK,
        ActionType.ASK,
        ActionType.CONVERSATION,
        ActionType.ATTACK,
        ActionType.GIVE_ITEM,
        ActionType.STEAL,
        ActionType.FOLLOW,
    }
)


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
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        text: str,
        *,
        recent_narrative: str = "",
        world_characters: list[Any] | None = None,
        pending_beat: str = "",
    ) -> ParsedIntent:
        intent: PlayerIntent | None = None
        degraded = True

        if (
            self.llm is not None
            and self.registry is not None
            and self.llm.usable_for(LLMRole.INTENT)
        ):
            try:
                context = await self.context_builder.build_intent_context(
                    uow,
                    state,
                    recent_narrative=recent_narrative,
                    world_characters=world_characters or [],
                    pending_beat=pending_beat,
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

        action, plan, notes = self.resolve(state, intent)
        return ParsedIntent(
            intent=intent,
            action=action,
            plan=plan,
            degraded=degraded,
            resolution_notes=notes,
        )

    # ------------------------------------------------------------------
    def rebind(self, state: WorldStateView, parsed: ParsedIntent, steward: Any) -> ParsedIntent:
        """Re-resolve an intent against a world the steward has just extended.

        The steward may have recognised what the player meant, or created it.
        Either way the entities exist in ``state`` now, so the ordinary binding
        pass is all that is needed - no special case downstream.
        """
        intent = parsed.intent.model_copy(deep=True)
        if steward.action_type is not None:
            # The steward decided last and knew most: it saw where the person
            # the player named actually is. When they are a valley away, the
            # honest reading of "go talk to them" is travel, not a failed
            # conversation with thin air.
            intent.action_type = steward.action_type
        if steward.target_id:
            intent.target_id = steward.target_id
            intent.target_key = steward.target_key
        # A destination the player actually named, and that the world actually
        # has, is not the steward's to overrule. Without this, "go to the
        # training ground and talk to her" walked to wherever *she* was,
        # because recognising the person also volunteered her location.
        if steward.location_key and state.graph.by_key(intent.location_key or "") is None:
            intent.location_key = steward.location_key
        if steward.utterance and not intent.utterance:
            intent.utterance = steward.utterance
        # A plan compiled against the old world would re-bind by luck at best.
        intent.plan = None

        # You cannot talk to someone who is a valley away. Rather than fail the
        # turn on a physical impossibility, walk there - the conversation is
        # still waiting on the other side, and the trip is the honest cost of
        # it. This is decided here rather than trusted to the model, which
        # tends to answer "go and talk" with a single TALK.
        #
        # The walk is only half of what the player asked for, though. Dropping
        # the rest is what made "go and talk to her" resolve as a bare MOVE:
        # no conversation, no relationship change, nothing the world could
        # remember - while the narrator, reading the same scene, wrote the
        # conversation anyway. So the original move is kept as a *deferred*
        # intent, and the caller plays it out as an ordinary second step once
        # the character has actually arrived.
        deferred: PlayerIntent | None = None
        destination = intent.location_key
        if (
            destination
            and destination != state.location_key()
            and intent.target_id
            and intent.action_type in DEFERRABLE_ACTIONS
            and not state.is_present(intent.target_id)
        ):
            deferred = intent.model_copy(deep=True)
            deferred.plan = None
            intent.action_type = ActionType.MOVE
            intent.target_id = None
            intent.target_key = None

        action, plan, notes = self.resolve(state, intent)
        return ParsedIntent(
            intent=intent,
            action=action,
            plan=plan,
            degraded=parsed.degraded,
            resolution_notes=list(
                dict.fromkeys([*parsed.resolution_notes, *notes])
            ),
            deferred_intent=deferred,
        )

    # ------------------------------------------------------------------
    def resolve(
        self, state: WorldStateView, intent: PlayerIntent
    ) -> tuple[Action, ActionPlan, list[str]]:
        """Bind every proposed primitive to real entities in the current scene."""
        notes: list[str] = []
        action = self._bind_action(state, intent, intent.raw_text, notes)

        if intent.plan is None:
            plan = ActionPlan(primitives=[ActionPrimitive(primitive_id="primary", action=action)])
            return action, plan, notes

        primitives: list[ActionPrimitive] = []
        seen: set[str] = set()
        invalid = False
        for proposed in intent.plan.primitives:
            if proposed.primitive_id in seen:
                notes.append(f"duplicate_primitive_id:{proposed.primitive_id}")
                invalid = True
                continue
            if (
                proposed.condition is not None
                and proposed.condition.primitive_id is not None
                and proposed.condition.primitive_id not in seen
            ):
                notes.append(
                    f"condition_requires_earlier_primitive:{proposed.condition.primitive_id}"
                )
                invalid = True
            if proposed.condition is not None:
                condition = proposed.condition
                if condition.target_id is not None and not state.is_present(condition.target_id):
                    notes.append(f"condition_target_not_present:{condition.target_id}")
                    invalid = True
                if condition.item_key is not None and self.pack.item(condition.item_key) is None:
                    notes.append(f"condition_unknown_item:{condition.item_key}")
                    invalid = True
                if (
                    condition.location_key is not None
                    and state.graph.by_key(condition.location_key) is None
                ):
                    notes.append(f"condition_unknown_location:{condition.location_key}")
                    invalid = True
            bound = self._bind_action(state, proposed, intent.raw_text, notes)
            primitives.append(
                ActionPrimitive(
                    primitive_id=proposed.primitive_id,
                    action=bound,
                    condition=proposed.condition,
                )
            )
            seen.add(proposed.primitive_id)

        if any(p.action.action_type in QUERY_ACTIONS for p in primitives):
            notes.append("query_action_cannot_be_in_plan")
            invalid = True
        if any(p.action.action_type is ActionType.MOVE for p in primitives[:-1]):
            notes.append("movement_must_be_last_primitive")
            invalid = True
        if invalid or len(primitives) < 2:
            intent.ambiguity = "invalid_action_plan"
            fallback = action.model_copy(update={"action_type": ActionType.CUSTOM})
            return (
                fallback,
                ActionPlan(primitives=[ActionPrimitive(primitive_id="primary", action=fallback)]),
                notes,
            )
        return primitives[0].action, ActionPlan(primitives=primitives), notes

    def _bind_action(
        self,
        state: WorldStateView,
        proposed: PlayerIntent | ActionPrimitiveIntent,
        raw_text: str,
        notes: list[str],
    ) -> Action:
        """Resolve one primitive without allowing invented identifiers."""

        target_id: str | None = None
        if proposed.target_id:
            if state.is_present(proposed.target_id):
                target_id = proposed.target_id
            else:
                notes.append(f"target_id_not_present:{proposed.target_id}")
        if target_id is None and proposed.target_key:
            character = state.character_by_key(proposed.target_key)
            if character is not None:
                target_id = character.id
            else:
                notes.append(f"target_key_not_present:{proposed.target_key}")

        target_location_id: str | None = None
        if proposed.location_key:
            location = state.graph.by_key(proposed.location_key)
            if location is not None:
                target_location_id = location.id
            else:
                notes.append(f"unknown_location:{proposed.location_key}")

        item_key = proposed.item_key
        if item_key and self.pack.item(item_key) is None:
            notes.append(f"unknown_item:{item_key}")
            item_key = None

        skill_key = proposed.skill_key
        if skill_key and self.pack.skill(skill_key) is None:
            notes.append(f"unknown_skill:{skill_key}")
            skill_key = None

        quest_id: str | None = None
        if proposed.quest_key:
            quest = next((q for q in state.active_quests if q.key == proposed.quest_key), None)
            if quest is not None:
                quest_id = quest.id
            else:
                notes.append(f"unknown_quest:{proposed.quest_key}")

        action_type = proposed.action_type
        if action_type is ActionType.MOVE and target_location_id is None:
            action_type = ActionType.CUSTOM
            notes.append("move_without_destination")

        return Action(
            action_type=action_type,
            actor_id=state.player.id,
            target_id=target_id,
            target_location_id=target_location_id,
            item_key=item_key,
            skill_key=skill_key,
            quest_id=quest_id,
            quantity=proposed.quantity,
            duration_minutes=proposed.duration_minutes,
            method=str(proposed.method) if proposed.method else None,
            style=proposed.style,
            request_size=proposed.request_size,
            goal=proposed.goal,
            utterance=proposed.utterance or (raw_text if _is_social(action_type) else None),
            raw_text=raw_text,
            parameters=dict(proposed.parameters),
        )

    # ------------------------------------------------------------------
    @staticmethod
    def is_query(action: Action) -> bool:
        return action.action_type in QUERY_ACTIONS


def _is_social(action_type: ActionType) -> bool:
    return action_type in (ActionType.TALK, ActionType.ASK, ActionType.CONVERSATION)

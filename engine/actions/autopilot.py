"""Autopilot - the player handing the pen back for a moment.

The interesting decisions in a story are rare. Everything between them is
travel, errands, waiting for the right hour, and following through on what was
already agreed. Making the player type all of it turns a novel into a chore
list, so ``继续`` lets the character keep acting in character until the scene
raises something that genuinely needs them.

This never decides an *outcome*: it produces an ordinary intent, which the same
rules, RNG and NPCs adjudicate as if the player had typed it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from engine.actions.schema import ActionGoal, PlayerIntent
from engine.contentpack.pack import ContentPack
from engine.core.errors import LLMError, StructuredOutputError
from engine.core.logging import get_logger
from engine.core.types import ActionType, LLMRole
from engine.world.state_view import WorldStateView

logger = get_logger("autopilot")


class AutopilotChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action_type: ActionType = ActionType.WAIT
    target_key: str | None = None
    location_key: str | None = None
    item_key: str | None = None
    skill_key: str | None = None
    duration_minutes: int | None = None
    utterance: str | None = None
    reason: str = ""


class AutopilotRun(BaseModel):
    """A short stretch of the character's own initiative.

    Planned in one call rather than one call per step: the model is the slow
    part of a turn, and a run that costs five round trips before the player
    reads a word is not an improvement over asking them to type five times.
    Steps are still executed - and re-validated - one at a time.
    """

    model_config = ConfigDict(extra="ignore")

    intent: str = ""
    steps: list[AutopilotChoice] = Field(default_factory=list, max_length=6)


class Autopilot:
    def __init__(
        self,
        pack: ContentPack,
        llm: Any = None,
        registry: Any = None,
        prompt_version: str = "v1",
    ) -> None:
        self.pack = pack
        self.llm = llm
        self.registry = registry
        self.prompt_version = prompt_version

    def usable(self) -> bool:
        return bool(
            self.llm and self.registry and self.llm.usable_for(LLMRole.DIRECTOR)
        )

    async def plan_run(
        self,
        state: WorldStateView,
        *,
        steps: int,
        recent_narrative: str = "",
        player_input: str = "",
        player_did: str = "",
    ) -> tuple[list[PlayerIntent], str]:
        """Plan a short stretch of action *in service of what the player asked*.

        This is the difference between a companion and a hijacker. Without
        ``player_input`` the planner falls back on the character's standing
        goals, which is how "go see what that notice says" turned into a
        morning of unrelated errands. The player's own words come first; the
        standing goals only fill the silence when they said nothing.

        The returned intents are proposals like any other: each is re-bound and
        re-adjudicated against the world as it stands when its turn comes, and
        the run stops the moment something needs the player.
        """
        if not self.usable():
            intent, _ = await self.choose(state, recent_narrative=recent_narrative)
            return [intent], ""

        try:
            prompt = self.registry.render(
                "autopilot_run",
                self.prompt_version,
                schema=self.llm.schema_hint(AutopilotRun),
                max_steps=str(max(1, steps)),
                player_input=player_input or "-",
                player_did=player_did or "-",
                **self._scene(state, recent_narrative),
            )
            run = await self.llm.generate_structured(
                LLMRole.DIRECTOR, AutopilotRun, prompt, prompt_version=self.prompt_version
            )
        except (LLMError, StructuredOutputError) as exc:
            logger.warning("autopilot run planning failed: %s", exc)
            self.llm.record_degraded(LLMRole.DIRECTOR, str(exc))
            intent, _ = await self.choose(state, recent_narrative=recent_narrative)
            return [intent], ""

        intents = [
            self._to_intent(state, self._keep_it_possible(state, choice))
            for choice in run.steps[: max(1, steps)]
        ]
        if not intents:
            intent, _ = await self.choose(state, recent_narrative=recent_narrative)
            return [intent], run.intent.strip()
        return intents, run.intent.strip()

    async def choose(
        self, state: WorldStateView, *, recent_narrative: str = ""
    ) -> tuple[PlayerIntent, str]:
        """Pick the character's next in-character move. Falls back to resting."""
        fallback = PlayerIntent(
            action_type=ActionType.CULTIVATE,
            actor_id=state.player.id,
            raw_text="",
            confidence=0.5,
        )
        if not self.usable():
            return fallback, ""

        try:
            prompt = self.registry.render(
                "autopilot",
                self.prompt_version,
                schema=self.llm.schema_hint(AutopilotChoice),
                **self._scene(state, recent_narrative),
            )
            choice = await self.llm.generate_structured(
                LLMRole.DIRECTOR,
                AutopilotChoice,
                prompt,
                prompt_version=self.prompt_version,
            )
        except (LLMError, StructuredOutputError) as exc:
            logger.warning("autopilot fell back to a quiet turn: %s", exc)
            self.llm.record_degraded(LLMRole.DIRECTOR, str(exc))
            return fallback, ""

        choice = self._keep_it_possible(state, choice)
        return self._to_intent(state, choice), choice.reason.strip()

    # ------------------------------------------------------------------
    def _scene(self, state: WorldStateView, recent_narrative: str) -> dict[str, str]:
        ladder = self.pack.realms
        return {
            "action_types": ", ".join(str(a) for a in ActionType),
            "player_summary": (
                f"{state.player.name} / "
                f"{ladder.display(state.player.realm, state.player.realm_stage)}"
            ),
            "location": state.location.name if state.location else "-",
            "location_key": state.location_key(),
            "time_label": state.time.label,
            "present_characters": "\n".join(
                f"- {c.display_name}[{c.key}]"
                for c in state.present_characters
                if c.alive
            )
            or "-",
            "player_goals": "\n".join(f"- {g}" for g in state.player.short_term_goals)
            or "-",
            "skill_keys": ", ".join(sorted({s.skill_key for s in state.known_skills}))
            or "-",
            "item_keys": ", ".join(sorted({r.item_key for r in state.inventory}))
            or "-",
            "active_quests": "\n".join(
                f"- {q.name} ({q.status})" for q in state.active_quests
            )
            or "-",
            "known_locations": "\n".join(
                f"- {loc.name}[{loc.key}]"
                for loc in state.graph.all()
                if loc.accessible
            )
            or "-",
            "recent_narrative": recent_narrative[-900:] or "-",
        }

    def _to_intent(
        self, state: WorldStateView, choice: AutopilotChoice
    ) -> PlayerIntent:
        return PlayerIntent(
            action_type=choice.action_type,
            actor_id=state.player.id,
            target_key=choice.target_key,
            location_key=choice.location_key,
            item_key=choice.item_key,
            skill_key=choice.skill_key,
            duration_minutes=choice.duration_minutes,
            utterance=choice.utterance,
            goal=ActionGoal(type="other", details=choice.reason[:200]),
            raw_text="",
            confidence=0.9,
        )

    def _keep_it_possible(
        self, state: WorldStateView, choice: AutopilotChoice
    ) -> AutopilotChoice:
        """Never spend the player's turn on something they cannot do.

        A refusal the player chose is a story. A refusal the autopilot walked
        into on their behalf is just a wasted turn, so the two cases the model
        gets wrong most often are corrected here rather than trusted to the
        prompt.
        """
        if choice.action_type is ActionType.USE_SKILL and not state.has_skill(
            choice.skill_key or ""
        ):
            logger.info("autopilot picked an unlearned skill; resting instead")
            return choice.model_copy(
                update={"action_type": ActionType.CULTIVATE, "skill_key": None}
            )
        if choice.action_type is ActionType.USE_ITEM and not state.inventory_quantity(
            choice.item_key or ""
        ):
            logger.info("autopilot picked an item the player lacks; observing instead")
            return choice.model_copy(
                update={"action_type": ActionType.OBSERVE, "item_key": None}
            )
        return choice

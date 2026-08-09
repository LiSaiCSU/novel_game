"""NarrativeRenderer (Prompt sections 26, 27, 49).

Runs last, on a world that is already decided and already committed. It writes
prose about facts; it cannot create, kill, reward, promote or reveal anything.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from engine.actions.schema import ActionOutcome
from engine.contentpack.pack import ContentPack
from engine.context.builder import ContextBuilder
from engine.core.errors import LLMError
from engine.core.logging import get_logger
from engine.core.models import Character
from engine.core.ports import UnitOfWork
from engine.core.types import LLMRole
from engine.narrative.style import NarrativeStyle, StyleReport
from engine.narrative.template_renderer import TemplateNarrativeRenderer
from engine.world.state_view import WorldStateView

logger = get_logger("narrative")


@dataclass(slots=True)
class NarrativeResult:
    text: str
    degraded: bool
    style_report: StyleReport | None = None
    prompt_tokens: int = 0
    debug: dict[str, object] = field(default_factory=dict)


class NarrativeRenderer:
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
        self.style = NarrativeStyle(pack)
        self.template = TemplateNarrativeRenderer(pack)

    # ------------------------------------------------------------------
    async def render(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        outcome: ActionOutcome,
        *,
        player_action: str,
        npc_lines: list[str],
        world_lines: list[str],
        recent_narrative: str,
        npc_decisions_summary: str = "",
    ) -> NarrativeResult:
        fallback = self.template.render(
            state, outcome, npc_lines=npc_lines, world_lines=world_lines
        )

        if outcome.summary_key.startswith("query_"):
            # Pure lookups are rendered from data, never narrated.
            return NarrativeResult(text=fallback, degraded=False)

        if not (self.llm and self.registry and self.llm.usable_for(LLMRole.NARRATIVE)):
            return NarrativeResult(text=fallback, degraded=True)

        try:
            prompt = await self._prompt(
                uow,
                state,
                outcome,
                player_action=player_action,
                npc_decisions_summary=npc_decisions_summary or "\n".join(npc_lines),
                world_lines=world_lines,
                recent_narrative=recent_narrative,
            )
            response = await self.llm.generate_text(
                LLMRole.NARRATIVE, prompt, prompt_version=self.prompt_version
            )
            text = response.text.strip()
        except LLMError as exc:
            logger.warning("narrative generation failed, using templates: %s", exc)
            self.llm.record_degraded(LLMRole.NARRATIVE, str(exc))
            return NarrativeResult(text=fallback, degraded=True)

        if not text:
            return NarrativeResult(text=fallback, degraded=True)

        report = self.style.review(text, self._known_entities(state))
        self.style.observe(text)
        return NarrativeResult(
            text=text,
            degraded=False,
            style_report=report,
            prompt_tokens=response.usage.prompt_tokens,
            debug={
                "overused": report.overused,
                "unknown_entities": report.unknown_entities,
                "length": report.length,
            },
        )

    # ------------------------------------------------------------------
    async def stream(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        outcome: ActionOutcome,
        *,
        player_action: str,
        npc_lines: list[str],
        world_lines: list[str],
        recent_narrative: str,
    ) -> AsyncIterator[str]:
        """Streaming is presentation only - the world was committed before this."""
        if not (self.llm and self.registry and self.llm.usable_for(LLMRole.NARRATIVE)):
            yield self.template.render(
                state, outcome, npc_lines=npc_lines, world_lines=world_lines
            )
            return
        prompt = await self._prompt(
            uow,
            state,
            outcome,
            player_action=player_action,
            npc_decisions_summary="\n".join(npc_lines),
            world_lines=world_lines,
            recent_narrative=recent_narrative,
        )
        collected: list[str] = []
        try:
            async for chunk in self.llm.stream_text(
                LLMRole.NARRATIVE, prompt, prompt_version=self.prompt_version
            ):
                collected.append(chunk)
                yield chunk
        except LLMError as exc:
            logger.warning("narrative stream failed: %s", exc)
            if not collected:
                yield self.template.render(
                    state, outcome, npc_lines=npc_lines, world_lines=world_lines
                )
            return
        self.style.observe("".join(collected))

    # ------------------------------------------------------------------
    async def _prompt(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        outcome: ActionOutcome,
        *,
        player_action: str,
        npc_decisions_summary: str,
        world_lines: list[str],
        recent_narrative: str,
    ) -> str:
        context = await self.context_builder.build_narrative_context(
            uow,
            state,
            player_action=player_action,
            resolved_result=self._resolved(outcome),
            npc_decisions=npc_decisions_summary,
            world_events="\n".join(world_lines) or "-",
            recent_narrative=recent_narrative,
        )
        sections = dict(context.sections)
        sections.update(self.style.as_prompt_vars())
        return self.registry.render("narrative", self.prompt_version, **sections)

    def _resolved(self, outcome: ActionOutcome) -> str:
        """The canonical result, stated flatly so the model cannot reinterpret it."""
        lines = [
            f"action: {outcome.action_type}",
            f"succeeded: {outcome.success}",
            f"time cost (minutes): {outcome.time_cost_minutes}",
        ]
        for key, value in outcome.facts.items():
            if key in ("breakdown", "path"):
                continue
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def _known_entities(self, state: WorldStateView) -> set[str]:
        names: set[str] = {state.player.name}
        for c in state.present_characters:
            names.add(c.name)
            if c.title:
                names.add(c.title)
        for loc in state.graph.all():
            names.add(loc.name)
        for item in self.pack.items:
            names.add(str(item.get("name", "")))
        for skill in self.pack.skills:
            names.add(str(skill.get("name", "")))
        for faction in self.pack.factions:
            names.add(str(faction.get("name", "")))
        return names

    def npc_line(self, npc: Character, speech_intent: str, spoken: str | None) -> str:
        return self.template.npc_line(npc, speech_intent, spoken)

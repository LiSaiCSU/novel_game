"""NarrativeRenderer (Prompt sections 26, 27, 49).

Runs last, on a world that is already decided and already committed. It writes
prose about facts; it cannot create, kill, reward, promote or reveal anything.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from pydantic import ValidationError

from engine.actions.schema import ActionOutcome
from engine.contentpack.pack import ContentPack
from engine.context.builder import ContextBuilder
from engine.core.errors import LLMError, StructuredOutputError
from engine.core.logging import get_logger
from engine.core.models import Character
from engine.core.ports import UnitOfWork
from engine.core.types import LLMRole
from engine.llm.structured import extract_json
from engine.narrative.fact_guard import NarrativeFactGuard
from engine.narrative.style import NarrativeStyle, StyleReport
from engine.narrative.template_renderer import TemplateNarrativeRenderer
from engine.orchestrator.turn import DEFAULT_NARRATIVE_CHARS, StoryBeat
from engine.world.state_view import WorldStateView

logger = get_logger("narrative")


#: The narrator writes prose, then this marker, then a compact JSON beat. One
#: call produces both, and the prose stays streamable up to the marker.
BEAT_MARKER = "---BEAT---"


@dataclass(slots=True)
class NarrativeResult:
    text: str
    degraded: bool
    beat: StoryBeat | None = None
    style_report: StyleReport | None = None
    prompt_tokens: int = 0
    debug: dict[str, object] = field(default_factory=dict)


def split_beat(raw: str) -> tuple[str, StoryBeat | None]:
    """Separate scene prose from the trailing beat block.

    A missing or malformed block is not an error: the caller falls back to the
    deterministic choices, and the player still gets their scene.
    """
    prose, marker, tail = raw.partition(BEAT_MARKER)
    prose = prose.strip()
    if not marker:
        return prose, None
    try:
        payload = extract_json(tail)
        beat = StoryBeat.model_validate(
            {
                "needs_player": bool(payload.get("needs_player", True)),
                "question": str(payload.get("question", "")).strip(),
                "options": [
                    {"label": str(o)[:40]} if isinstance(o, str) else
                    {
                        "label": str(o.get("label", ""))[:40],
                        "hint": str(o.get("hint", ""))[:120],
                    }
                    for o in (payload.get("options") or [])[:4]
                ],
            }
        )
    except (StructuredOutputError, ValidationError, AttributeError, TypeError) as exc:
        logger.warning("narrative beat block unusable: %s", exc)
        return prose, None
    beat.options = [o for o in beat.options if o.label]
    return prose, beat


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
        self.fact_guard = NarrativeFactGuard(pack)
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
        max_chars: int = DEFAULT_NARRATIVE_CHARS,
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
                max_chars=max_chars,
            )
            response = await self.llm.generate_text(
                LLMRole.NARRATIVE,
                prompt,
                prompt_version=self.prompt_version,
                max_output_tokens=self.style.output_token_budget(
                    max_chars,
                    self.registry.get("narrative", self.prompt_version).max_output_tokens,
                ),
            )
            text = response.text.strip()
        except LLMError as exc:
            logger.warning("narrative generation failed, using templates: %s", exc)
            self.llm.record_degraded(LLMRole.NARRATIVE, str(exc))
            return NarrativeResult(text=fallback, degraded=True)

        prose, beat = split_beat(text)
        prose = self.style.enforce_max_chars(prose, max_chars)
        if not prose:
            return NarrativeResult(text=fallback, degraded=True)

        fact_violations = self.fact_guard.review(
            state, player_action=player_action, prose=prose
        )
        if fact_violations:
            logger.warning(
                "narrative violated declared facts, using templates: %s",
                [violation.as_dict() for violation in fact_violations],
            )
            return NarrativeResult(
                text=fallback,
                degraded=True,
                debug={
                    "fact_violations": [
                        violation.as_dict() for violation in fact_violations
                    ]
                },
            )

        report = self.style.review(prose, self._known_entities(state))
        self.style.observe(prose)
        return NarrativeResult(
            text=prose,
            degraded=False,
            beat=beat,
            style_report=report,
            prompt_tokens=response.usage.prompt_tokens,
            debug={
                "overused": report.overused,
                "unknown_entities": report.unknown_entities,
                "length": report.length,
                "beat": beat.model_dump(mode="json") if beat else None,
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
        max_chars: int = DEFAULT_NARRATIVE_CHARS,
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
            max_chars=max_chars,
        )
        collected: list[str] = []
        try:
            async for chunk in self.llm.stream_text(
                LLMRole.NARRATIVE,
                prompt,
                prompt_version=self.prompt_version,
                max_output_tokens=self.style.output_token_budget(
                    max_chars,
                    self.registry.get("narrative", self.prompt_version).max_output_tokens,
                ),
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
        max_chars: int,
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
        sections.update(self.style.as_prompt_vars(max_chars))
        return self.registry.render("narrative", self.prompt_version, **sections)

    def _resolved(self, outcome: ActionOutcome) -> str:
        """The canonical result, stated flatly so the model cannot reinterpret it."""
        payload = outcome.model_dump(mode="json", exclude={"events"})
        facts = dict(payload.get("facts") or {})
        facts.pop("breakdown", None)
        facts.pop("path", None)
        payload["facts"] = facts
        return json.dumps(payload, ensure_ascii=False, indent=2)

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

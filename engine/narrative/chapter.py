"""Writing a whole stretch of story as one chapter.

Narrating each committed step on its own produces two problems at once: it
costs one model round trip per step, and it reads like a changelog - five
paragraphs that each restate where you are and what you just did.

So the world runs ahead deterministically for a few steps, and the chapter is
written once, over all of it. That is cheaper *and* better: the prose can skip
the boring middle, compress four hours of walking into a clause, and land on
whatever it was that made the run stop.

Like every renderer here, this one writes about facts that are already
committed. It cannot change an outcome, only tell it well.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from engine.actions.schema import ActionOutcome
from engine.contentpack.pack import ContentPack
from engine.context.builder import ContextBuilder
from engine.core.errors import LLMError
from engine.core.logging import get_logger
from engine.core.ports import UnitOfWork
from engine.core.types import LLMRole
from engine.narrative.renderer import BEAT_MARKER, NarrativeRenderer, split_beat
from engine.narrative.style import filter_repeated_paragraphs, strip_repeated_opening
from engine.orchestrator.interrupt import Interrupt
from engine.orchestrator.turn import DEFAULT_NARRATIVE_CHARS, StoryBeat
from engine.world.state_view import WorldStateView

logger = get_logger("chapter")

#: Receives prose as it is written, so the player can start reading before the
#: chapter is finished.
ChunkListener = Callable[[str], Awaitable[None]]

#: How much of the previous chapter the prompt is shown. It is there so the
#: opening line can connect to what just happened - not so the model can
#: summarise it. Handing over whole chapters reliably produces a chapter that
#: opens by retelling them, and the de-duplication pass then has to delete
#: prose the reader already watched stream in.
PROMPT_CONTINUITY_CHARS = 700


def _continuity_tail(recent_narrative: str, limit: int = PROMPT_CONTINUITY_CHARS) -> str:
    """The last few paragraphs of what came before, cut on a paragraph break."""
    text = recent_narrative.strip()
    if len(text) <= limit:
        return text
    tail = text[-limit:]
    _, separator, remainder = tail.partition("\n\n")
    return (remainder if separator else tail).strip()


@dataclass(slots=True)
class ChapterStep:
    """One committed step, reduced to what a narrator needs to know."""

    #: What the character did, in the player's words or the autopilot's.
    action: str
    outcome: ActionOutcome
    npc_lines: list[str] = field(default_factory=list)
    world_lines: list[str] = field(default_factory=list)
    by_player: bool = False
    minutes: int = 0

    def summarise(self, index: int) -> str:
        """A compact, language-neutral dossier. The prompt supplies the words."""
        rows = [f"[{index}] {self.action or self.outcome.summary_key}"]
        rows.append(f"    result: {self.outcome.summary_key} success={self.outcome.success}")
        facts = {
            k: v
            for k, v in self.outcome.facts.items()
            if isinstance(v, (str, int, float, bool)) and k not in ("breakdown",)
        }
        if facts:
            rows.append(f"    facts: {facts}")
        if self.minutes:
            rows.append(f"    minutes: {self.minutes}")
        for line in self.npc_lines:
            rows.append(f"    npc: {line}")
        for line in self.world_lines:
            rows.append(f"    world: {line}")
        return "\n".join(rows)


@dataclass(slots=True)
class ChapterResult:
    text: str
    beat: StoryBeat | None = None
    degraded: bool = False
    debug: dict[str, Any] = field(default_factory=dict)


class ChapterRenderer:
    def __init__(
        self,
        pack: ContentPack,
        context_builder: ContextBuilder,
        renderer: NarrativeRenderer,
        llm: Any = None,
        registry: Any = None,
        prompt_version: str = "v1",
    ) -> None:
        self.pack = pack
        self.context_builder = context_builder
        self.renderer = renderer
        self.llm = llm
        self.registry = registry
        self.prompt_version = prompt_version

    # ------------------------------------------------------------------
    async def render(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        steps: list[ChapterStep],
        *,
        interrupt: Interrupt | None,
        recent_narrative: str,
        told_already: str = "",
        arc: str = "",
        on_chunk: ChunkListener | None = None,
        max_chars: int = DEFAULT_NARRATIVE_CHARS,
    ) -> ChapterResult:
        fallback = self._fallback(state, steps)
        if not steps:
            return ChapterResult(text=fallback, degraded=True)
        if not (self.llm and self.registry and self.llm.usable_for(LLMRole.NARRATIVE)):
            return ChapterResult(text=fallback, degraded=True)

        try:
            context = await self.context_builder.build_narrative_context(
                uow,
                state,
                player_action=steps[0].action,
                resolved_result="\n".join(step.summarise(i + 1) for i, step in enumerate(steps)),
                npc_decisions="\n".join(line for step in steps for line in step.npc_lines) or "-",
                world_events="\n".join(line for step in steps for line in step.world_lines) or "-",
                recent_narrative=_continuity_tail(recent_narrative),
            )
            sections = dict(context.sections)
            sections.update(self.renderer.style.as_prompt_vars(max_chars))
            sections.update(
                {
                    "beat_marker": BEAT_MARKER,
                    "arc": arc or "-",
                    "step_count": str(len(steps)),
                    "elapsed": self._elapsed(state, steps),
                    "player_led": "yes" if steps and steps[0].by_player else "no",
                    "stop_reason": self._stop_reason(interrupt),
                }
            )
            prompt = self.registry.render("chapter", self.prompt_version, **sections)
            # The prompt is given only the tail, to keep the context small and
            # to give the model less to copy. De-duplication reaches further
            # back than that: a chapter that re-tells a scene from three
            # chapters ago is exactly the failure worth catching.
            raw = await self._generate(
                prompt, on_chunk, max_chars, told_already or recent_narrative
            )
        except LLMError as exc:
            logger.warning("chapter generation failed, using templates: %s", exc)
            self.llm.record_degraded(LLMRole.NARRATIVE, str(exc))
            return ChapterResult(text=fallback, degraded=True)

        prose, beat = split_beat(raw)
        prose = self.renderer.style.enforce_max_chars(prose, max_chars)
        if not prose:
            return ChapterResult(text=fallback, degraded=True)

        fact_violations = self.renderer.fact_guard.review(
            state,
            player_action="\n".join(step.action for step in steps if step.action),
            prose=prose,
        )
        if fact_violations:
            logger.warning(
                "chapter violated declared facts, using templates: %s",
                [violation.as_dict() for violation in fact_violations],
            )
            return ChapterResult(
                text=fallback,
                degraded=True,
                debug={
                    "steps": len(steps),
                    "fact_violations": [violation.as_dict() for violation in fact_violations],
                },
            )

        report = self.renderer.style.review(prose, self.renderer._known_entities(state))
        self.renderer.style.observe(prose)
        return ChapterResult(
            text=prose,
            beat=beat,
            debug={
                "steps": len(steps),
                "overused": report.overused,
                "unknown_entities": report.unknown_entities,
                "length": report.length,
                "beat": beat.model_dump(mode="json") if beat else None,
            },
        )

    # ------------------------------------------------------------------
    def _declared_budget(self) -> int | None:
        """The output budget this prompt file asks for, if it asks for one."""
        try:
            return self.registry.get("chapter", self.prompt_version).max_output_tokens
        except Exception:  # a missing template surfaces at render time
            return None

    async def _generate(
        self,
        prompt: str,
        on_chunk: ChunkListener | None,
        max_chars: int,
        recent_narrative: str,
    ) -> str:
        """Produce the chapter, streaming the prose when someone is watching.

        The beat block is machine-readable bookkeeping, so it is withheld: only
        text ahead of the marker is emitted, and a marker-length tail is always
        held back in case the marker itself is split across two chunks.
        """
        # A chapter is 1500-2500 characters; the router's per-role default is
        # sized for a single scene and would truncate it. The budget the
        # prompt file declares for itself is the one that applies here.
        budget = self.renderer.style.output_token_budget(max_chars, self._declared_budget())
        if on_chunk is None:
            response = await self.llm.generate_text(
                LLMRole.NARRATIVE,
                prompt,
                prompt_version=self.prompt_version,
                max_output_tokens=budget,
            )
            prose, beat = split_beat(response.text)
            prose = strip_repeated_opening(prose, recent_narrative)
            if beat is None:
                return prose
            return f"{prose}\n\n{BEAT_MARKER}\n{beat.model_dump_json()}"

        collected: list[str] = []
        emitted = 0
        streamed_visible = ""
        ceiling = int(self.renderer.style.as_prompt_vars(max_chars)["max_length"])
        stream_limit = max(0, ceiling - 180)
        async for chunk in self.llm.stream_text(
            LLMRole.NARRATIVE,
            prompt,
            prompt_version=self.prompt_version,
            max_output_tokens=budget,
        ):
            collected.append(chunk)
            full = "".join(collected)
            head, marker, _ = full.partition(BEAT_MARKER)
            safe_head = head if marker else head[: max(0, len(head) - len(BEAT_MARKER))]
            safe = filter_repeated_paragraphs(
                safe_head,
                recent_narrative,
                final=bool(marker),
            )[:stream_limit]
            if not safe.startswith(streamed_visible):
                logger.warning("stream continuation filter became non-monotonic; holding output")
                safe = streamed_visible
            if len(safe) > emitted:
                await on_chunk(safe[emitted:])
                emitted = len(safe)
                streamed_visible = safe
        raw = "".join(collected)
        prose, beat = split_beat(raw)
        prose = filter_repeated_paragraphs(prose, recent_narrative, final=True)
        final_prose = self.renderer.style.enforce_max_chars(prose, max_chars)
        if not final_prose.startswith(streamed_visible):
            logger.warning("final continuation differs from streamed prose; preserving visible text")
            final_prose = streamed_visible
        if len(final_prose) > emitted:
            await on_chunk(final_prose[emitted:])
        if beat is None:
            return final_prose
        return f"{final_prose}\n\n{BEAT_MARKER}\n{beat.model_dump_json()}"

    def _elapsed(self, state: WorldStateView, steps: list[ChapterStep]) -> str:
        total = sum(step.minutes for step in steps)
        unit, count = state.clock.duration_parts(total)
        template = (self.pack.narrative_templates.get("duration", {}) or {}).get(unit, "")
        return template.replace("{n}", str(count)) if template else str(total)

    def _stop_reason(self, interrupt: Interrupt | None) -> str:
        if interrupt is None:
            return "-"
        who = "、".join(interrupt.involves) if interrupt.involves else ""
        return f"{interrupt.reason}{(' / ' + who) if who else ''} ({interrupt.detail})"

    def _fallback(self, state: WorldStateView, steps: list[ChapterStep]) -> str:
        """Terse but honest, exactly like the single-turn template path."""
        parts: list[str] = []
        for step in steps:
            parts.append(
                self.renderer.template.render(
                    state,
                    step.outcome,
                    npc_lines=step.npc_lines,
                    world_lines=step.world_lines,
                )
            )
        return "\n\n".join(p for p in parts if p)

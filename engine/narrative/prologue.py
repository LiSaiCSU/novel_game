"""The opening scene.

A sandbox with no first page is not freedom, it is a blank stare. The player
arrives knowing nothing about who they are, what is wrong here, or what they
could possibly type - so they type 打坐修炼 forever.

The prologue fixes that once, at session start: it says who you are, what this
place is like today, what is already in motion, and what you could do about it.
The goals it names are written to the character, so the autopilot and the
director have something to pull against from turn one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.contentpack.pack import ContentPack
from engine.context.builder import ContextBuilder
from engine.core.errors import LLMError
from engine.core.logging import get_logger
from engine.core.ports import UnitOfWork
from engine.core.types import LLMRole
from engine.llm.structured import extract_json
from engine.narrative.renderer import BEAT_MARKER, split_beat
from engine.narrative.style import NarrativeStyle
from engine.orchestrator.turn import (
    DEFAULT_NARRATIVE_CHARS,
    MAX_NARRATIVE_CHARS,
    MIN_NARRATIVE_CHARS,
    StoryBeat,
)
from engine.world.state_view import WorldStateView

logger = get_logger("prologue")


@dataclass(slots=True)
class PrologueResult:
    text: str
    beat: StoryBeat | None = None
    goals: list[str] = field(default_factory=list)
    degraded: bool = False


class Prologue:
    def __init__(
        self,
        pack: ContentPack,
        context_builder: ContextBuilder,
        llm: Any = None,
        registry: Any = None,
        prompt_version: str = "v1",
    ) -> None:
        self.pack = pack
        self.context_builder = context_builder
        self.llm = llm
        self.registry = registry
        self.prompt_version = prompt_version

    async def write(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        *,
        max_chars: int = DEFAULT_NARRATIVE_CHARS,
    ) -> PrologueResult:
        fallback = self._fallback(state)
        if not (self.llm and self.registry and self.llm.usable_for(LLMRole.NARRATIVE)):
            return PrologueResult(text=fallback, degraded=True)

        ladder = self.pack.realms
        profile = self.pack.vocabulary.get("profile_labels", {}) or {}
        try:
            visible_facts = await self.context_builder.visible_player_facts(uow, state)
            prompt = self.registry.render(
                "prologue",
                self.prompt_version,
                beat_marker=BEAT_MARKER,
                world_name=self.pack.name,
                player_name=state.player.name,
                # Field labels stay neutral; the prompt supplies the wording,
                # the engine only supplies the values.
                player_summary=(
                    f"{state.player.name} / {state.player.age}{profile.get('age_suffix', '')}"
                    f" / {profile.get('realm', 'realm')}: "
                    f"{ladder.display(state.player.realm, state.player.realm_stage)}"
                    f" / {profile.get('root', 'root')}: {state.player.spiritual_root or '-'}"
                    f" / {profile.get('faction', 'faction')}: "
                    f"{state.faction_name(state.player.faction_key) or '-'}"
                ),
                player_background=state.player.background or "-",
                location=state.location.name if state.location else "-",
                location_description=(
                    state.location.description if state.location else "-"
                ),
                time_label=state.time.label,
                # The same identity block the chapter renderer gets. Without
                # it the opening invents personalities that later chapters
                # then contradict - the reader sees a different person.
                present_characters=self.context_builder.people_for_narrative(state),
                nearby_locations="\n".join(
                    f"- {loc.name}: {loc.description}"
                    for key in state.graph.neighbours(state.location_key())
                    if (loc := state.graph.by_key(key)) is not None
                )
                or "-",
                target_length=self._length_vars(max_chars)[0],
                max_length=self._length_vars(max_chars)[1],
                story_premise=str(self.pack.story.get("premise", "")) or "-",
                story_lead=self._story_lead(state),
                relationship_boundaries=(
                    str(self.pack.story.get("relationship_boundaries", "")) or "-"
                ),
                visible_facts=visible_facts,
                plot_hooks="\n".join(
                    f"- {t.name}: {t.next_beat_hint}"
                    for t in state.plot_threads[:5]
                    if t.next_beat_hint
                )
                or "-",
            )
            # The opening chapter is long by design; the router's per-role
            # default would cut it off. Honour the prompt's own budget.
            response = await self.llm.generate_text(
                LLMRole.NARRATIVE,
                prompt,
                prompt_version=self.prompt_version,
                max_output_tokens=self._output_budget(max_chars),
            )
        except LLMError as exc:
            logger.warning("prologue generation failed: %s", exc)
            self.llm.record_degraded(LLMRole.NARRATIVE, str(exc))
            return PrologueResult(text=fallback, degraded=True)

        prose, beat = split_beat(response.text)
        prose = NarrativeStyle.enforce_max_chars(prose, max_chars)
        if not prose:
            return PrologueResult(text=fallback, degraded=True)
        return PrologueResult(text=prose, beat=beat, goals=_goals(response.text))

    def _fallback(self, state: WorldStateView) -> str:
        parts = [str(self.pack.story.get("premise", ""))]
        parts.append(state.location.description if state.location else "")
        parts.append(self.pack.narrative_templates.get("query", {}).get("status_header", ""))
        return "\n\n".join(p for p in parts if p)

    def _story_lead(self, state: WorldStateView) -> str:
        key = str(state.player.metadata.get("story_lead_key", ""))
        lead = state.character_by_key(key)
        profile = self.pack.vocabulary.get("profile_labels", {}) or {}
        if lead is None:
            return str(profile.get("no_story_lead", "-"))
        ladder = self.pack.realms
        return (
            f"{lead.display_name} / {profile.get(lead.gender, lead.gender)} / "
            f"{ladder.display(lead.realm, lead.realm_stage)} / "
            f"{lead.faction_rank or '-'} | {lead.personality.speech_style} | "
            f"{lead.background}"
        )

    def _length_vars(self, max_chars: int) -> tuple[str, str]:
        ceiling = max(
            MIN_NARRATIVE_CHARS,
            min(MAX_NARRATIVE_CHARS, int(max_chars or DEFAULT_NARRATIVE_CHARS)),
        )
        return str(max(MIN_NARRATIVE_CHARS, int(ceiling * 0.85))), str(ceiling)

    def _output_budget(self, max_chars: int) -> int:
        declared = self.registry.get("prologue", self.prompt_version).max_output_tokens
        return NarrativeStyle.output_token_budget(max_chars, declared)


def _goals(raw: str) -> list[str]:
    """The beat block may also name what the character wants. Optional."""
    _, marker, tail = raw.partition(BEAT_MARKER)
    if not marker:
        return []
    try:
        payload = extract_json(tail)
    except Exception:
        return []
    goals = payload.get("goals") if isinstance(payload, dict) else None
    if not isinstance(goals, list):
        return []
    return [str(g).strip()[:80] for g in goals[:3] if str(g).strip()]

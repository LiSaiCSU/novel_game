"""PlotSteward - the part of the engine that lets the *story* change shape.

The world steward lets a player reach for a place or a person the pack never
wrote down. This is the same idea one level up: it lets a player reach for a
story the pack never wrote down.

A content pack ships the storylines its author imagined. A player who decides
to take over the coaching inn instead of digging for their father is not off
the rails - they have started a story nobody wrote, and until the engine can
see it, the director keeps pushing the authored line, the endings keep scoring
against threads the player abandoned, and every prompt keeps insisting the
real story is somewhere the player left. That is the shape "I have freedom but
it does not matter" actually takes.

So the steward may:

* open a thread, with a clock, for something the player has committed to;
* refocus - raise what the player keeps pursuing, lower what they keep walking
  past;
* abandon a thread the player has explicitly refused.

The division of labour matches the world steward's. The model reads what the
player did and proposes; this module decides what is *allowed*, clamps every
field, and hands ordinary changes to the ordinary transaction. Endings already
score against thread status and stage, so a thread opening or closing changes
which endings are reachable without anything here knowing what an ending is.

It never decides outcomes, never creates people or items, and never touches a
thread the player has not actually engaged with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.errors import LLMError, StructuredOutputError
from engine.core.logging import get_logger
from engine.core.models import PlotThread, StoryClock
from engine.core.mutations import StateChange
from engine.core.types import ClockKind, LLMRole, ThreadStatus
from engine.world import clocks as clock_service
from engine.world.state_view import WorldStateView

logger = get_logger("plot-steward")

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: One turn may open one storyline. A player who says three ambitious things
#: in one sentence has still only changed direction once.
MAX_NEW_THREADS_PER_TURN = 1
MAX_REFOCUS_PER_TURN = 3
#: A player-opened thread starts below the authored spine. It earns its way up
#: by being pursued, rather than displacing the story on the strength of one
#: sentence.
MAX_NEW_THREAD_IMPORTANCE = 0.7
MIN_THREAD_IMPORTANCE = 0.05


class ThreadDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = ""
    name: str = ""
    importance: float = 0.5
    unresolved_questions: list[str] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    next_beat_hint: str = ""
    #: Optional pressure to attach, so a new storyline is legible the same way
    #: the authored ones are.
    clock_name: str = ""
    clock_kind: str = "project"
    clock_segments: int = 4
    clock_consequence: str = ""


class ThreadRefocus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = ""
    #: ``pursue`` raises importance, ``ignore`` lowers it, ``abandon`` closes
    #: the thread outright.
    intent: str = "pursue"
    reason: str = ""


class PlotPlan(BaseModel):
    """What the model thinks the player's action did to the shape of the story."""

    model_config = ConfigDict(extra="ignore")

    #: The steward must be able to say nothing. Most turns change no direction.
    direction_changed: bool = False
    reading: str = ""
    new_thread: ThreadDraft | None = None
    refocus: list[ThreadRefocus] = Field(default_factory=list)


@dataclass(slots=True)
class PlotResult:
    reading: str = ""
    changes: list[StateChange] = field(default_factory=list)
    opened: list[str] = field(default_factory=list)
    refocused: list[str] = field(default_factory=list)
    abandoned: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    consulted: bool = False
    degraded: bool = False

    @property
    def changed_direction(self) -> bool:
        return bool(self.opened or self.refocused or self.abandoned)

    def as_dict(self) -> dict[str, Any]:
        return {
            "reading": self.reading,
            "opened": self.opened,
            "refocused": self.refocused,
            "abandoned": self.abandoned,
            "notes": self.notes,
            "consulted": self.consulted,
            "degraded": self.degraded,
        }


class PlotSteward:
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
        return bool(self.llm and self.registry and self.llm.usable_for(LLMRole.DIRECTOR))

    # ==================================================================
    async def review(
        self,
        state: WorldStateView,
        *,
        player_action: str,
        recent_narrative: str,
    ) -> PlotResult:
        """Ask whether what the player just did changed where the story is going."""
        if not self.usable() or not player_action.strip():
            return PlotResult()
        try:
            prompt = self.registry.render(
                "plot_steward",
                self.prompt_version,
                player_action=player_action[:1200],
                recent_narrative=recent_narrative[-1200:] or "-",
                threads=self._threads_for_prompt(state),
                story_clocks=clock_service.clocks_for_prompt(state),
                present_characters=self._people_for_prompt(state),
                schema=PlotPlan.model_json_schema(),
                common_constraints=self.registry.common_constraints(),
            )
            plan = await self.llm.generate_structured(
                LLMRole.DIRECTOR,
                prompt,
                PlotPlan,
                prompt_version=self.prompt_version,
            )
        except (LLMError, StructuredOutputError) as exc:
            logger.warning("plot steward unavailable, story shape unchanged: %s", exc)
            return PlotResult(consulted=True, degraded=True)

        return self._validate(state, plan)

    # ==================================================================
    def _validate(self, state: WorldStateView, plan: PlotPlan) -> PlotResult:
        result = PlotResult(reading=plan.reading[:300], consulted=True)
        if not plan.direction_changed:
            return result

        existing = {thread.key: thread for thread in state.plot_threads}
        if plan.new_thread is not None and len(result.opened) < MAX_NEW_THREADS_PER_TURN:
            self._open_thread(state, plan.new_thread, existing, result)

        for entry in plan.refocus[:MAX_REFOCUS_PER_TURN]:
            self._refocus(state, entry, existing, result)
        return result

    def _open_thread(
        self,
        state: WorldStateView,
        draft: ThreadDraft,
        existing: dict[str, PlotThread],
        result: PlotResult,
    ) -> None:
        key = draft.key.strip().lower()
        if not _KEY_RE.fullmatch(key):
            result.notes.append("rejected new thread: malformed key")
            return
        if key in existing:
            result.notes.append(f"rejected new thread {key}: already exists")
            return
        name = draft.name.strip()[:200]
        if not name:
            result.notes.append(f"rejected new thread {key}: no name")
            return
        # Participants must be people the world already has. A storyline is
        # allowed to be new; the cast is not.
        known = {character.key for character in state.present_characters} | {state.player.key}
        participants = [item for item in draft.participants if item in known][:8]
        importance = max(
            MIN_THREAD_IMPORTANCE, min(MAX_NEW_THREAD_IMPORTANCE, float(draft.importance))
        )

        thread = PlotThread(
            world_id=state.world.id,
            key=key,
            name=name,
            status=ThreadStatus.ACTIVE,
            importance=importance,
            stage=0,
            participants=participants,
            unresolved_questions=[q.strip()[:160] for q in draft.unresolved_questions[:4] if q.strip()],
            last_advanced_minute=state.world.current_minute,
            next_beat_hint=draft.next_beat_hint.strip()[:240],
            escalation_pressure=0.2,
            metadata={"opened_by": "player"},
        )
        result.changes.append(mut.plot_thread_spawn(thread, reason="player_direction"))
        result.opened.append(key)

        clock_name = draft.clock_name.strip()[:200]
        if not clock_name:
            return
        try:
            kind = ClockKind(draft.clock_kind)
        except ValueError:
            kind = ClockKind.PROJECT
        clock = StoryClock(
            world_id=state.world.id,
            key=f"clock_{key}"[:120],
            name=clock_name,
            kind=kind,
            segments=max(2, min(8, int(draft.clock_segments))),
            # Player-opened pressure is never a wall-clock deadline: the
            # engine has no basis for choosing how long the player has.
            minutes_per_segment=0,
            started_at_minute=state.world.current_minute,
            thread_key=key,
            consequence=draft.clock_consequence.strip()[:240],
        )
        if any(item.key == clock.key for item in state.clocks):
            return
        result.changes.append(mut.clock_spawn(clock, reason="player_direction"))

    def _refocus(
        self,
        state: WorldStateView,
        entry: ThreadRefocus,
        existing: dict[str, PlotThread],
        result: PlotResult,
    ) -> None:
        thread = existing.get(entry.key.strip().lower())
        if thread is None or thread.status is not ThreadStatus.ACTIVE:
            return
        if entry.intent == "abandon":
            result.changes.append(
                mut.plot_thread_update(
                    thread.id,
                    {"status": str(ThreadStatus.ABANDONED)},
                    reason=f"player_abandoned:{entry.reason[:120]}",
                )
            )
            result.abandoned.append(thread.key)
            # Pressure attached to a story nobody is telling any more is noise
            # on the dial, so it comes down with the thread.
            for clock in state.clocks:
                if clock.thread_key == thread.key:
                    result.changes.append(
                        clock_service.close(clock, reason="thread_abandoned")
                    )
            return

        step = 0.15 if entry.intent == "pursue" else -0.15
        after = max(MIN_THREAD_IMPORTANCE, min(1.0, thread.importance + step))
        if abs(after - thread.importance) < 0.01:
            return
        result.changes.append(
            mut.plot_thread_update(
                thread.id,
                {"importance": after, "last_advanced_minute": state.world.current_minute},
                reason=f"player_{entry.intent}",
            )
        )
        result.refocused.append(thread.key)

    # ==================================================================
    def _threads_for_prompt(self, state: WorldStateView) -> str:
        rows = []
        for thread in sorted(state.plot_threads, key=lambda t: -t.importance):
            if thread.status is not ThreadStatus.ACTIVE:
                continue
            opened = "player" if thread.metadata.get("opened_by") == "player" else "author"
            rows.append(
                f"- {thread.key} | {thread.name} | importance={thread.importance:.2f}"
                f" | stage={thread.stage} | origin={opened}"
            )
        return "\n".join(rows) or "-"

    def _people_for_prompt(self, state: WorldStateView) -> str:
        # The player heads the list; the prompt says so, so the engine does not
        # have to carry a word for "player" in any particular language.
        rows = [f"- {state.player.key} | {state.player.display_name}"]
        rows.extend(
            f"- {character.key} | {character.display_name}"
            for character in state.present_characters
            if character.alive
        )
        return "\n".join(rows)

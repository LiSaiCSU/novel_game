"""ContextBuilder (Prompt sections 29, 30).

Each agent gets its own view, assembled deliberately and trimmed to a token
budget. Never ``SELECT * FROM world``.

The NPC path is the single most safety-critical function in the codebase: it is
what stops characters from knowing things they were never told.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.contentpack.pack import ContentPack
from engine.core.models import Character, Event, Relationship
from engine.core.ports import UnitOfWork
from engine.core.types import CharacterType
from engine.knowledge.service import Belief, KnowledgeService
from engine.llm.provider import estimate_tokens
from engine.memory.embeddings import Embedder
from engine.memory.retrieval import MemoryRetriever, ScoredMemory
from engine.world.state_view import WorldStateView


@dataclass(slots=True)
class BuiltContext:
    """A rendered context plus the accounting needed for the debug panel."""

    sections: dict[str, str] = field(default_factory=dict)
    estimated_tokens: int = 0
    truncated: list[str] = field(default_factory=list)
    included_fact_keys: list[str] = field(default_factory=list)
    included_memory_ids: list[str] = field(default_factory=list)

    def get(self, name: str, default: str = "") -> str:
        return self.sections.get(name, default)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sections": self.sections,
            "estimated_tokens": self.estimated_tokens,
            "truncated": self.truncated,
            "fact_keys": self.included_fact_keys,
            "memory_ids": self.included_memory_ids,
        }


class ContextBuilder:
    #: Trim order: the last entry is dropped first, identity is never dropped.
    _NPC_TRIM_ORDER = ("recent_events", "memories", "relationships", "known_facts")

    def __init__(
        self,
        pack: ContentPack,
        knowledge: KnowledgeService,
        retriever: MemoryRetriever,
        embedder: Embedder,
        budgets: dict[str, int] | None = None,
    ) -> None:
        self.pack = pack
        self.knowledge = knowledge
        self.retriever = retriever
        self.embedder = embedder
        self.budgets = budgets or {}

    def budget(self, name: str, default: int) -> int:
        return int(self.budgets.get(name, default))

    # ==================================================================
    # NPC
    # ==================================================================
    async def build_npc_context(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        npc: Character,
        *,
        situation: str = "",
        query: str = "",
        available_actions: list[str] | None = None,
    ) -> BuiltContext:
        pack = self.pack
        ladder = pack.realms
        present = [c for c in state.present_characters if c.id != npc.id and c.alive]
        if state.player.alive and state.player.id != npc.id:
            present = [*present, state.player]

        # --- what this character actually believes -----------------------
        beliefs = await self.knowledge.beliefs_of(uow, npc.id)
        hedges = self.knowledge.hedges()

        # --- relationships, restricted to who is standing here ------------
        relationships: list[tuple[Character, Relationship | None]] = []
        for other in present:
            rel = await uow.relationships.get(npc.id, other.id)
            relationships.append((other, rel))

        # --- memories, composite-ranked ----------------------------------
        stored = await uow.memories.list_for_owner(npc.id)
        scored = await self.retriever.retrieve(
            stored,
            query=query or situation,
            now_minute=state.world.current_minute,
            related_character_ids=[c.id for c in present],
            context_terms=[c.name for c in present],
        )

        # --- events this character could actually perceive ----------------
        recent = await uow.events.list_recent(state.world.id, limit=40)
        perceived = [e for e in recent if self._perceived_by(e, npc)][-8:]

        sections: dict[str, str] = {
            "identity": self._identity(npc, ladder),
            "personality": self._personality(npc),
            "values": ", ".join(npc.personality.values) or "-",
            "taboos": ", ".join(npc.personality.taboos) or "-",
            "speech_style": npc.personality.speech_style or "-",
            "risk_tolerance": f"{npc.personality.risk_tolerance:.2f}",
            "long_term_goal": npc.long_term_goal or "-",
            "short_term_goals": self._bullets(npc.short_term_goals),
            "current_emotion": self._emotion(npc),
            "condition": self._condition(npc),
            "known_facts": self._beliefs(beliefs, hedges),
            "relationships": self._relationships(relationships),
            "memories": self._memories(scored),
            "location": state.location.name if state.location else "-",
            "time_label": state.time.label,
            "present_characters": ", ".join(c.display_name for c in present) or "-",
            "situation": situation or "-",
            "recent_events": self._events(perceived),
            "available_actions": self._bullets(available_actions or []),
        }

        built = BuiltContext(
            sections=sections,
            included_fact_keys=[b.fact_key for b in beliefs],
            included_memory_ids=[s.memory.id for s in scored],
        )
        self._enforce_budget(built, self.budget("npc", 2500), self._NPC_TRIM_ORDER)
        return built

    # ==================================================================
    # Narrative
    # ==================================================================
    async def build_narrative_context(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        *,
        player_action: str,
        resolved_result: str,
        npc_decisions: str,
        world_events: str,
        recent_narrative: str,
    ) -> BuiltContext:
        style = self.pack.narrative_style
        # The viewpoint is the player: only what the player could know may appear.
        beliefs = await self.knowledge.beliefs_of(uow, state.player.id)
        hedges = self.knowledge.hedges()

        sections = {
            "language": str(style.get("language", "")),
            "person": str(style.get("person", "")),
            "tense": str(style.get("tense", "")),
            "target_length": str(style.get("target_length", 300)),
            "tone": str(style.get("tone", "")),
            "location": state.location.name if state.location else "-",
            "time_label": state.time.label,
            "atmosphere": state.location.description if state.location else "-",
            # Names alone are not enough to write a person. Without rank and
            # manner the narrator guesses, and an outer-sect disciple ends up
            # described as a servant - which readers notice immediately.
            "visible_characters": self.people_for_narrative(state),
            "recent_narrative": recent_narrative or "-",
            "player_action": player_action,
            "resolved_result": resolved_result,
            "npc_decisions": npc_decisions or "-",
            "world_events": world_events or "-",
            "visible_facts": self._beliefs(beliefs, hedges),
        }
        built = BuiltContext(sections=sections, included_fact_keys=[b.fact_key for b in beliefs])
        self._enforce_budget(
            built, self.budget("narrative", 3500), ("recent_narrative", "visible_facts")
        )
        return built

    # ==================================================================
    # Director
    # ==================================================================
    async def build_director_context(
        self, uow: UnitOfWork, state: WorldStateView, *, turns_since_last_event: int
    ) -> BuiltContext:
        world = state.world
        ladder = self.pack.realms
        majors = [
            c
            for c in await uow.characters.list_for_world(world.id, alive_only=False)
            if c.character_type is CharacterType.MAJOR_NPC
        ]
        threads = await uow.plot_threads.list_for_world(world.id)
        recent = await uow.events.list_recent(world.id, limit=25)
        important = [e for e in recent if e.importance >= 0.3][-10:]
        quests = await uow.quests.list_for_world(world.id)
        scheduled_director = await uow.director_events.list_for_world(
            world.id, status="SCHEDULED", limit=20
        )
        outstanding = [
            q for q in quests if str(q.status) in ("offered", "active")
        ]

        sections = {
            "world_summary": (
                f"{world.name}: {world.description[:280]}" if world.description else world.name
            ),
            "time_label": state.time.label,
            "tension": f"{world.narrative_tension:.1f}",
            "tension_history": ", ".join(f"{t:.0f}" for t in world.tension_history[-8:]) or "-",
            "turns_since_last_event": str(turns_since_last_event),
            "player_progress": (
                f"{state.player.name} / {ladder.display(state.player.realm, state.player.realm_stage)} "
                f"/ {state.location.name if state.location else '-'}"
            ),
            "major_characters": self._major_characters(majors, ladder),
            "plot_threads": self._threads(threads),
            "recent_events": self._events(important, with_ids=True),
            "outstanding": self._bullets(
                [f"{q.key}: {q.name} ({q.status})" for q in outstanding]
                + [
                    f"director:{event.event_type} @{event.scheduled_for_minute} "
                    f"thread={event.source_plot_thread_key or '-'}"
                    for event in scheduled_director
                ]
            ),
            "event_types": ", ".join(
                str(t) for t in (self.pack.rule("director.allowed_event_types", []) or [])
            ),
        }
        built = BuiltContext(sections=sections)
        self._enforce_budget(
            built, self.budget("director", 3000), ("recent_events", "major_characters")
        )
        return built

    # ==================================================================
    # Intent
    # ==================================================================
    async def build_intent_context(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        *,
        recent_narrative: str,
        world_characters: list[Character] | None = None,
        pending_beat: str = "",
    ) -> BuiltContext:
        world_characters = world_characters or []
        ladder = self.pack.realms
        sections = {
            "location": state.location.name if state.location else "-",
            "time_label": state.time.label,
            "player_summary": (
                f"{state.player.name} / {ladder.display(state.player.realm, state.player.realm_stage)}"
            ),
            "present_characters": self._present_for_intent(state),
            # The whole map, not just the doorstep. Naming a place the player
            # has heard of is not a parse error, it is a travel plan - and the
            # movement rules already know how to route there.
            "known_locations": self._location_index(state),
            "elsewhere_characters": self._elsewhere_for_intent(state, world_characters),
            "inventory_keys": ", ".join(sorted({r.item_key for r in state.inventory})) or "-",
            "skill_keys": ", ".join(sorted({r.skill_key for r in state.known_skills})) or "-",
            # The player is almost always answering the end of the last
            # chapter, so it has to survive intact - a truncated tail loses the
            # very hook they are reaching for.
            "recent_narrative": recent_narrative[-2500:] or "-",
            "pending_beat": pending_beat or "-",
        }
        built = BuiltContext(sections=sections)
        self._enforce_budget(
            built,
            self.budget("intent", 2600),
            ("elsewhere_characters", "known_locations", "recent_narrative"),
        )
        return built

    def _location_index(self, state: WorldStateView) -> str:
        """Every location in the world, with the reachable ones marked.

        Annotations stay language-neutral: the engine ships no prose, and the
        prompt that consumes this explains the notation.
        """
        here = state.location_key()
        neighbours = state.graph.neighbours(here)
        rows: list[str] = []
        for loc in state.graph.all():
            if loc.key == here:
                rows.append(f"- {loc.name}[{loc.key}] (HERE)")
            elif loc.key in neighbours:
                rows.append(f"- {loc.name}[{loc.key}] ({neighbours[loc.key]}min)")
            elif loc.accessible:
                rows.append(f"- {loc.name}[{loc.key}]")
        return "\n".join(rows) or "-"

    def _elsewhere_for_intent(
        self, state: WorldStateView, world_characters: list[Character]
    ) -> str:
        """People who exist but are not here - naming them is a plan, not an error."""
        present = {c.id for c in state.present_characters} | {state.player.id}
        rows = [
            f"- {c.display_name}[{c.key}] (at {c.location_key or '?'})"
            for c in world_characters
            if c.alive and c.id not in present
        ]
        return "\n".join(rows) or "-"

    # ==================================================================
    # Memory extraction
    # ==================================================================
    def people_for_narrative(self, state: WorldStateView) -> str:
        """Who is here, in enough detail to write them consistently."""
        rows: list[str] = []
        for c in state.present_characters:
            if not c.alive:
                continue
            bits = [
                c.display_name,
                c.gender,
                self.pack.realms.display(c.realm, c.realm_stage),
            ]
            if c.faction_rank:
                bits.append(c.faction_rank)
            row = " / ".join(b for b in bits if b)
            if c.personality.speech_style:
                row += f" | {c.personality.speech_style}"
            rel = state.relationship_with(c.id)
            if rel is not None:
                dims = ", ".join(f"{k}={v}" for k, v in rel.as_dict().items() if v)
                if dims:
                    row += f" | {dims}"
            rows.append(f"- {row}")
        return "\n".join(rows) or "-"

    async def build_memory_context(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        owner: Character,
        *,
        event_description: str,
        participants: list[Character],
        perceived: str,
    ) -> BuiltContext:
        existing = await uow.memories.list_for_owner(owner.id, limit=40)
        scored = await self.retriever.retrieve(
            existing,
            query=event_description,
            now_minute=state.world.current_minute,
            related_character_ids=[c.id for c in participants],
            top_k=4,
        )
        sections = {
            "owner": f"{owner.display_name} ({owner.key})",
            "event": event_description,
            "participants": ", ".join(f"{c.display_name}[{c.key}]" for c in participants) or "-",
            "location": state.location.name if state.location else "-",
            "time_label": state.time.label,
            "perceived": perceived or event_description,
            "existing_memories": self._memories(scored),
        }
        built = BuiltContext(
            sections=sections, included_memory_ids=[s.memory.id for s in scored]
        )
        self._enforce_budget(built, self.budget("memory", 1200), ("existing_memories",))
        return built

    # ==================================================================
    # Rendering helpers
    # ==================================================================
    def _identity(self, npc: Character, ladder) -> str:
        bits = [
            f"name: {npc.display_name} ({npc.key})",
            f"age: {npc.age}",
            f"tier: {ladder.display(npc.realm, npc.realm_stage)}",
        ]
        if npc.faction_key:
            rank = f"/{npc.faction_rank}" if npc.faction_rank else ""
            bits.append(f"affiliation: {npc.faction_key}{rank}")
        if npc.background:
            bits.append(f"background: {npc.background.strip()}")
        return "\n".join(bits)

    def _personality(self, npc: Character) -> str:
        if not npc.personality.traits:
            return "-"
        return ", ".join(
            f"{name}={value:.2f}" for name, value in sorted(npc.personality.traits.items())
        )

    def _emotion(self, npc: Character) -> str:
        e = npc.current_emotion
        return f"{e.dominant} (valence={e.valence:+.2f}, arousal={e.arousal:.2f}, intensity={e.intensity:.2f})"

    def _condition(self, npc: Character) -> str:
        return (
            f"health {npc.health}/{npc.max_health}, "
            f"spiritual power {npc.spiritual_power}/{npc.max_spiritual_power}, "
            f"injuries {npc.injuries:.2f}, mental state {npc.mental_state:.2f}"
        )

    def _beliefs(self, beliefs: list[Belief], hedges: dict[str, str]) -> str:
        if not beliefs:
            return "-"
        return "\n".join(
            f"- {b.as_prompt_line(hedges)} (confidence {b.confidence:.2f})" for b in beliefs
        )

    def _relationships(self, pairs: list[tuple[Character, Relationship | None]]) -> str:
        if not pairs:
            return "-"
        lines: list[str] = []
        for other, rel in pairs:
            if rel is None:
                lines.append(f"- {other.display_name} [{other.key}]: a stranger")
                continue
            dims = ", ".join(f"{k}={v}" for k, v in rel.as_dict().items() if v)
            lines.append(f"- {other.display_name} [{other.key}]: {dims or 'neutral'}")
        return "\n".join(lines)

    def _memories(self, scored: list[ScoredMemory]) -> str:
        if not scored:
            return "-"
        return "\n".join(
            f"- [{s.memory.memory_type}] {s.memory.summary} "
            f"(importance {s.memory.importance:.2f})"
            for s in scored
        )

    def _events(self, events: list[Event], *, with_ids: bool = False) -> str:
        if not events:
            return "-"
        lines: list[str] = []
        for e in events:
            prefix = f"[{e.id}] " if with_ids else ""
            detail = e.payload.get("summary") or e.payload.get("reason") or ""
            lines.append(f"- {prefix}{e.event_type} @{e.world_minute} {detail}".rstrip())
        return "\n".join(lines)

    def _threads(self, threads) -> str:
        if not threads:
            return "-"
        lines = []
        for t in threads:
            questions = "; ".join(t.unresolved_questions[:2])
            lines.append(
                f"- [{t.key}] {t.name} (status={t.status}, stage={t.stage}, "
                f"importance={t.importance:.2f}) open: {questions or '-'}"
            )
        return "\n".join(lines)

    def _major_characters(self, majors: list[Character], ladder) -> str:
        if not majors:
            return "-"
        lines = []
        for c in majors:
            status = "alive" if c.alive else "DEAD"
            lines.append(
                f"- [{c.key}] {c.display_name} ({ladder.display(c.realm, c.realm_stage)}, "
                f"{status}, at {c.location_key or 'unknown'}) goal: {c.long_term_goal or '-'}"
            )
        return "\n".join(lines)

    def _present_for_intent(self, state: WorldStateView) -> str:
        if not state.present_characters:
            return "-"
        return "\n".join(
            f"- {c.display_name} (id={c.id}, key={c.key})"
            for c in state.present_characters
            if c.alive
        )

    def _bullets(self, values: list[str]) -> str:
        return "\n".join(f"- {v}" for v in values) if values else "-"

    # ==================================================================
    def _enforce_budget(
        self, built: BuiltContext, budget: int, trim_order: tuple[str, ...]
    ) -> None:
        """Trim the least essential sections until the estimate fits."""
        built.estimated_tokens = self._estimate(built)
        for section in reversed(trim_order):
            if built.estimated_tokens <= budget:
                break
            body = built.sections.get(section, "")
            if not body or body == "-":
                continue
            lines = body.splitlines()
            while lines and built.estimated_tokens > budget:
                lines = lines[:-1]
                built.sections[section] = "\n".join(lines) if lines else "-"
                built.estimated_tokens = self._estimate(built)
            if section not in built.truncated:
                built.truncated.append(section)

    def _estimate(self, built: BuiltContext) -> int:
        return sum(estimate_tokens(v) for v in built.sections.values())

    def _perceived_by(self, event: Event, npc: Character) -> bool:
        """Visibility gate for the event feed - the same firewall as knowledge."""
        visibility = str(event.visibility)
        if visibility in ("SECRET", "PRIVATE"):
            return npc.id in event.witnesses or event.actor_id == npc.id
        if visibility == "FACTION":
            return npc.id in event.witnesses or bool(npc.faction_key)
        if visibility == "LOCAL":
            return npc.id in event.witnesses or event.location_id == npc.location_id
        return True

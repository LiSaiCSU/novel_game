"""MemoryExtractor (Prompt section 28).

A deterministic filter runs first: routine events are discarded without
spending a token. Only what survives is worth asking a model to summarise.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.characters.schemas import MemoryExtraction
from engine.contentpack.pack import ContentPack
from engine.context.builder import ContextBuilder
from engine.core.errors import LLMError, StructuredOutputError
from engine.core.logging import get_logger
from engine.core.models import Character, Event, Memory
from engine.core.ports import UnitOfWork
from engine.core.types import LLMRole, MemoryTag, MemoryType
from engine.memory.embeddings import Embedder
from engine.world.state_view import WorldStateView

logger = get_logger("memory")

#: Event types that map cleanly onto a memory tag without asking a model.
_EVENT_TAGS: dict[str, MemoryTag] = {
    "DEATH": MemoryTag.TRAUMA,
    "RESCUE": MemoryTag.RESCUE,
    "BETRAYAL": MemoryTag.BETRAYAL,
    "PROMISE": MemoryTag.PROMISE,
    "SECRET_DISCLOSURE": MemoryTag.SECRET_DISCLOSURE,
    "COMBAT_VICTORY": MemoryTag.VICTORY,
    "COMBAT_DEFEAT": MemoryTag.FAILURE,
    "BREAKTHROUGH": MemoryTag.VICTORY,
    "BREAKTHROUGH_FAILED": MemoryTag.FAILURE,
    "QUEST_COMPLETED": MemoryTag.VICTORY,
    "QUEST_FAILED": MemoryTag.FAILURE,
    "THEFT": MemoryTag.CONFLICT,
    "AMBUSH": MemoryTag.SHARED_DANGER,
    "CONFRONTATION": MemoryTag.CONFLICT,
    "TRADE": MemoryTag.GIFT,
    "CONVERSATION": MemoryTag.MAJOR_CONVERSATION,
}


@dataclass(slots=True)
class ExtractionResult:
    memories: list[Memory]
    degraded: bool
    skipped: list[str]


class MemoryExtractor:
    def __init__(
        self,
        pack: ContentPack,
        context_builder: ContextBuilder,
        embedder: Embedder,
        llm=None,
        registry=None,
        prompt_version: str = "v1",
    ) -> None:
        self.pack = pack
        self.context_builder = context_builder
        self.embedder = embedder
        self.llm = llm
        self.registry = registry
        self.prompt_version = prompt_version
        self.min_importance = float(pack.rule("memory.min_importance", 0.3))
        self.always = set(pack.rule("memory.always_remember_event_types", []) or [])

    # ------------------------------------------------------------------
    def worth_remembering(self, event: Event) -> bool:
        """The cheap gate. Small talk and errands never reach the model."""
        if event.event_type in self.always:
            return True
        return event.importance >= self.min_importance

    # ------------------------------------------------------------------
    async def extract(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        events: list[Event],
        *,
        owners: list[Character],
    ) -> ExtractionResult:
        memories: list[Memory] = []
        skipped: list[str] = []
        degraded = False

        for event in events:
            if not self.worth_remembering(event):
                skipped.append(f"{event.event_type}:below_threshold")
                continue
            participants = [
                c for c in owners if c.id == event.actor_id or c.id in event.target_ids
            ]
            witnesses = [c for c in owners if c.id in event.witnesses]
            for owner in {c.id: c for c in participants + witnesses}.values():
                if not owner.alive:
                    continue
                memory, was_degraded = await self._for_owner(uow, state, owner, event, owners)
                degraded = degraded or was_degraded
                if memory is not None:
                    memories.append(memory)
        return ExtractionResult(memories=memories, degraded=degraded, skipped=skipped)

    # ------------------------------------------------------------------
    async def _for_owner(
        self,
        uow: UnitOfWork,
        state: WorldStateView,
        owner: Character,
        event: Event,
        cast: list[Character],
    ) -> tuple[Memory | None, bool]:
        description = self._describe(event, cast)
        participants = [c for c in cast if c.id == event.actor_id or c.id in event.target_ids]

        # Memory is a rebuildable projection of a canonical Event.  Checking
        # this before any model or embedding call makes recovery cheap as well
        # as idempotent; the database constraint is the final concurrency guard.
        if await uow.memories.get_by_event(owner.id, event.id) is not None:
            return None, False

        extraction: MemoryExtraction | None = None
        degraded = True
        if self.llm is not None and self.registry is not None and self.llm.usable_for(LLMRole.MEMORY):
            try:
                context = await self.context_builder.build_memory_context(
                    uow,
                    state,
                    owner,
                    event_description=description,
                    participants=participants,
                    perceived=description,
                )
                prompt = self.registry.render(
                    "memory_extractor",
                    self.prompt_version,
                    schema=self.llm.schema_hint(MemoryExtraction),
                    **context.sections,
                )
                extraction = await self.llm.generate_structured(
                    LLMRole.MEMORY,
                    MemoryExtraction,
                    prompt,
                    prompt_version=self.prompt_version,
                )
                degraded = False
            except (LLMError, StructuredOutputError) as exc:
                logger.warning("memory extraction fell back to heuristics: %s", exc)
                self.llm.record_degraded(LLMRole.MEMORY, str(exc))

        if extraction is None:
            extraction = self._heuristic(event, description)

        if not extraction.should_store:
            return None, degraded

        # The model may classify and score the memory, but it cannot author a
        # new long-term fact.  Persist and embed only the canonical description
        # derived from the committed event, never the proposed prose summary.
        embedding = await self.embedder.embed(description)
        memory = Memory(
            world_id=state.world.id,
            owner_character_id=owner.id,
            memory_type=self._layer(extraction, owner, participants),
            memory_tag=extraction.memory_type,
            summary=description,
            importance=max(0.0, min(1.0, extraction.importance)),
            emotional_valence=extraction.emotional_valence,
            related_characters=[c.id for c in participants if c.id != owner.id],
            related_event_id=event.id,
            related_location_id=event.location_id,
            created_at_minute=event.world_minute,
            embedding=embedding,
        )
        return memory, degraded

    # ------------------------------------------------------------------
    def _heuristic(self, event: Event, description: str) -> MemoryExtraction:
        tag = _EVENT_TAGS.get(event.event_type, MemoryTag.OTHER)
        valence = 0.0
        if tag in (MemoryTag.RESCUE, MemoryTag.VICTORY, MemoryTag.GIFT):
            valence = 0.7
        elif tag in (MemoryTag.BETRAYAL, MemoryTag.TRAUMA, MemoryTag.FAILURE, MemoryTag.CONFLICT):
            valence = -0.7
        return MemoryExtraction(
            should_store=True,
            importance=event.importance,
            memory_type=tag,
            summary=description,
            emotional_valence=valence,
        )

    def _layer(
        self, extraction: MemoryExtraction, owner: Character, participants: list[Character]
    ) -> MemoryType:
        """Which of the four memory layers this belongs in (Prompt section 16)."""
        others = [c for c in participants if c.id != owner.id]
        if extraction.importance >= 0.85:
            return MemoryType.SEMANTIC
        if others:
            return MemoryType.RELATIONSHIP
        return MemoryType.EPISODIC

    def _describe(self, event: Event, cast: list[Character]) -> str:
        """A factual, content-neutral sentence about what happened."""
        names = {c.id: c.display_name for c in cast}
        actor = names.get(event.actor_id or "", event.actor_id or "?")
        summary = event.payload.get("summary")
        if isinstance(summary, str) and summary:
            return summary
        targets = ", ".join(names.get(t, t) for t in event.target_ids)
        parts = [f"{event.event_type}", f"actor={actor}"]
        if targets:
            parts.append(f"target={targets}")
        for key in ("realm_after", "damage", "item", "quest", "cost"):
            if key in event.payload:
                parts.append(f"{key}={event.payload[key]}")
        return " ".join(parts)

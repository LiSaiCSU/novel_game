"""Knowledge: truth versus belief (Prompt section 15).

The database knows whether a fact is true. A character knows only what that
character has learned. These are different tables on purpose, and the second
one is the only thing an NPC agent is ever shown.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.contentpack.pack import ContentPack
from engine.core import mutations as mut
from engine.core.models import Character, Fact
from engine.core.mutations import StateChange
from engine.core.ports import UnitOfWork
from engine.core.types import (
    VISIBLE_KNOWLEDGE_STATES,
    KnowledgeSource,
    KnowledgeState,
    Visibility,
)

#: Ordered from least to most committed, used when merging evidence.
_STRENGTH: dict[KnowledgeState, int] = {
    KnowledgeState.UNKNOWN: 0,
    KnowledgeState.HEARD: 1,
    KnowledgeState.SUSPECTED: 2,
    KnowledgeState.DISBELIEVED: 3,
    KnowledgeState.BELIEVED: 4,
    KnowledgeState.KNOWN: 5,
}


@dataclass(slots=True)
class Belief:
    """One thing a character holds to be (or suspects to be) the case."""

    fact_key: str
    statement: str
    state: KnowledgeState
    confidence: float
    source: KnowledgeSource
    learned_at_minute: int

    def as_prompt_line(self, hedges: dict[str, str]) -> str:
        """Render belief strength as language, never as a truth value."""
        hedge = hedges.get(str(self.state), "")
        return f"{hedge}{self.statement}".strip()


class KnowledgeService:
    def __init__(self, pack: ContentPack) -> None:
        self.pack = pack

    # ------------------------------------------------------------------
    async def beliefs_of(self, uow: UnitOfWork, character_id: str) -> list[Belief]:
        """Everything this character believes. UNKNOWN rows never appear."""
        rows = await uow.knowledge.list_known(character_id)
        beliefs: list[Belief] = []
        for knowledge, fact in rows:
            if knowledge.knowledge_state not in VISIBLE_KNOWLEDGE_STATES:
                continue
            beliefs.append(
                Belief(
                    fact_key=fact.key,
                    statement=fact.statement,
                    state=knowledge.knowledge_state,
                    confidence=knowledge.confidence,
                    source=knowledge.source,
                    learned_at_minute=knowledge.learned_at_minute,
                )
            )
        beliefs.sort(key=lambda b: (-_STRENGTH[b.state], -b.confidence))
        return beliefs

    async def knows(
        self,
        uow: UnitOfWork,
        character_id: str,
        fact_key: str,
        world_id: str,
        *,
        min_state: KnowledgeState = KnowledgeState.BELIEVED,
    ) -> bool:
        fact = await uow.knowledge.get_fact_by_key(world_id, fact_key)
        if fact is None:
            return False
        row = await uow.knowledge.get_knowledge(character_id, fact.id)
        if row is None:
            return False
        return _STRENGTH[row.knowledge_state] >= _STRENGTH[min_state]

    async def state_of(
        self, uow: UnitOfWork, character_id: str, fact_key: str, world_id: str
    ) -> KnowledgeState:
        fact = await uow.knowledge.get_fact_by_key(world_id, fact_key)
        if fact is None:
            return KnowledgeState.UNKNOWN
        row = await uow.knowledge.get_knowledge(character_id, fact.id)
        return row.knowledge_state if row else KnowledgeState.UNKNOWN

    # ------------------------------------------------------------------
    def learn(
        self,
        character_id: str,
        fact: Fact,
        *,
        state: KnowledgeState,
        confidence: float,
        source: KnowledgeSource,
        at_minute: int,
        from_character_id: str | None = None,
        reason: str = "",
    ) -> StateChange:
        return mut.knowledge_set(
            character_id,
            fact.id,
            str(state),
            max(0.0, min(1.0, confidence)),
            str(source),
            at_minute,
            source_character_id=from_character_id,
            reason=reason or f"learned:{fact.key}",
        )

    def witness(
        self, character_id: str, fact: Fact, at_minute: int, reason: str = ""
    ) -> StateChange:
        """Seeing it happen is the strongest evidence there is."""
        return self.learn(
            character_id,
            fact,
            state=KnowledgeState.KNOWN,
            confidence=1.0,
            source=KnowledgeSource.WITNESSED,
            at_minute=at_minute,
            reason=reason,
        )

    def told(
        self,
        listener_id: str,
        fact: Fact,
        *,
        teller_id: str,
        teller_credibility: float,
        at_minute: int,
        hops: int = 1,
    ) -> StateChange:
        """Hearsay degrades with each retelling (Prompt section 40)."""
        decay = float(self.pack.rule("information.confidence_decay_per_hop", 0.25))
        confidence = max(0.05, teller_credibility * (1.0 - decay) ** max(0, hops - 1))
        if confidence >= 0.75:
            state = KnowledgeState.BELIEVED
        elif confidence >= 0.4:
            state = KnowledgeState.SUSPECTED
        else:
            state = KnowledgeState.HEARD
        return self.learn(
            listener_id,
            fact,
            state=state,
            confidence=confidence,
            source=KnowledgeSource.TOLD_BY,
            at_minute=at_minute,
            from_character_id=teller_id,
            reason=f"told_by:{teller_id}",
        )

    # ------------------------------------------------------------------
    async def propagate(
        self,
        uow: UnitOfWork,
        world_id: str,
        *,
        days_elapsed: float,
        at_minute: int,
        rng,
        candidates: list[Character] | None = None,
    ) -> list[StateChange]:
        """Rumour drift. A secret told once does not become common knowledge.

        Nothing spreads if its visibility says it cannot: SECRET has a zero
        spread chance in the content pack, so private acts stay private until a
        character deliberately reveals them.
        """
        if days_elapsed <= 0:
            return []
        spread_cfg = self.pack.rule("information.spread_chance_per_day", {}) or {}
        people = candidates if candidates is not None else await uow.characters.list_for_world(world_id)
        alive = [c for c in people if c.alive]
        if len(alive) < 2:
            return []

        changes: list[StateChange] = []
        facts = {f.id: f for f in await uow.knowledge.list_facts(world_id)}
        for fact in facts.values():
            visibility = _visibility_for(fact)
            per_day = float(spread_cfg.get(str(visibility), 0.0))
            if per_day <= 0:
                continue
            chance = 1.0 - (1.0 - per_day) ** min(days_elapsed, 30.0)
            knowers = {row.character_id for row in await uow.knowledge.list_knowers(fact.id)}
            if not knowers:
                continue
            for person in alive:
                if person.id in knowers:
                    continue
                if not rng.chance(chance * 0.25):
                    continue
                changes.append(
                    self.learn(
                        person.id,
                        fact,
                        state=KnowledgeState.HEARD,
                        confidence=0.3,
                        source=KnowledgeSource.RUMOR,
                        at_minute=at_minute,
                        reason="rumour_spread",
                    )
                )
        return changes

    # ------------------------------------------------------------------
    async def match_facts(
        self, uow: UnitOfWork, world_id: str, text: str, *, threshold: float = 0.34
    ) -> list[tuple[Fact, float]]:
        """Which world facts is this utterance talking about?

        Character-bigram overlap: language-agnostic, no tokenizer, and good
        enough to notice that the player just named a secret out loud.
        """
        if not text or not text.strip():
            return []
        needle = _bigrams(text)
        if not needle:
            return []
        matches: list[tuple[Fact, float]] = []
        for fact in await uow.knowledge.list_facts(world_id):
            hay = _bigrams(fact.statement)
            if not hay:
                continue
            overlap = len(needle & hay) / len(hay)
            if overlap >= threshold:
                matches.append((fact, overlap))
        matches.sort(key=lambda pair: pair[1], reverse=True)
        return matches

    # ------------------------------------------------------------------
    def hedges(self) -> dict[str, str]:
        """Wording used to express belief strength in prompts, from content."""
        table = self.pack.narrative_templates.get("knowledge_hedges", {}) or {}
        return {str(k): str(v) for k, v in table.items()}


def _bigrams(text: str) -> set[str]:
    cleaned = "".join(ch for ch in text if not ch.isspace() and ch.isalnum())
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def _visibility_for(fact: Fact) -> Visibility:
    if fact.sensitivity >= 0.9:
        return Visibility.SECRET
    if fact.sensitivity >= 0.6:
        return Visibility.PRIVATE
    if str(fact.scope) == "FACTION":
        return Visibility.FACTION
    if str(fact.scope) == "PERSONAL":
        return Visibility.PRIVATE
    return Visibility.PUBLIC

"""Memory retrieval (Prompt section 16).

Explicitly *not* plain vector top-K. What a person recalls depends on how
important it was, how long ago, who is standing in front of them, and what is
being discussed - similarity is only one term of five.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from engine.contentpack.pack import ContentPack
from engine.core.models import Memory
from engine.memory.embeddings import Embedder, cosine


@dataclass(slots=True)
class ScoredMemory:
    memory: Memory
    score: float
    parts: dict[str, float]


class MemoryRetriever:
    def __init__(self, pack: ContentPack, embedder: Embedder) -> None:
        self.pack = pack
        self.embedder = embedder
        self.weights: dict[str, float] = {
            "similarity": 0.35,
            "importance": 0.25,
            "recency": 0.15,
            "relationship": 0.15,
            "context": 0.10,
            **(pack.rule("memory.retrieval_weights", {}) or {}),
        }
        self.half_life = float(pack.rule("memory.recency_half_life_minutes", 129_600))
        self.decay_floor = float(pack.rule("memory.decay_floor", 0.15))

    # ------------------------------------------------------------------
    async def retrieve(
        self,
        memories: list[Memory],
        *,
        query: str,
        now_minute: int,
        related_character_ids: list[str] | None = None,
        context_terms: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[ScoredMemory]:
        if not memories:
            return []
        k = top_k if top_k is not None else int(self.pack.rule("memory.top_k", 6))
        query_vector = await self.embedder.embed(query) if query else None
        related = set(related_character_ids or [])
        terms = [t for t in (context_terms or []) if t]

        scored: list[ScoredMemory] = []
        for memory in memories:
            parts = {
                "similarity": cosine(query_vector, memory.embedding) if query_vector else 0.0,
                "importance": max(0.0, min(1.0, memory.importance)),
                "recency": self._recency(memory, now_minute),
                "relationship": self._relationship(memory, related),
                "context": self._context(memory, terms),
            }
            score = sum(self.weights.get(name, 0.0) * value for name, value in parts.items())
            score *= max(self.decay_floor, memory.decay)
            scored.append(ScoredMemory(memory=memory, score=score, parts=parts))

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]

    # ------------------------------------------------------------------
    def _recency(self, memory: Memory, now_minute: int) -> float:
        elapsed = max(0, now_minute - memory.created_at_minute)
        if self.half_life <= 0:
            return 1.0
        return 0.5 ** (elapsed / self.half_life)

    def _relationship(self, memory: Memory, related: set[str]) -> float:
        if not related or not memory.related_characters:
            return 0.0
        overlap = len(related & set(memory.related_characters))
        return min(1.0, overlap / len(related))

    def _context(self, memory: Memory, terms: list[str]) -> float:
        if not terms:
            return 0.0
        haystack = memory.summary
        hits = sum(1 for term in terms if term and term in haystack)
        return min(1.0, hits / len(terms))

    def decay_for(self, memory: Memory, now_minute: int) -> float:
        """How faded a memory has become; recall refreshes it."""
        base = self._recency(memory, now_minute)
        reinforcement = min(0.5, memory.recall_count * 0.05)
        return max(self.decay_floor, min(1.0, base + reinforcement + memory.importance * 0.3))


def summarize_scores(scored: list[ScoredMemory]) -> list[dict[str, object]]:
    """Debug-panel view of why each memory surfaced."""
    return [
        {
            "summary": s.memory.summary,
            "type": str(s.memory.memory_type),
            "score": round(s.score, 4),
            "parts": {k: round(v, 4) for k, v in s.parts.items()},
        }
        for s in scored
    ]


def log_odds(probability: float) -> float:
    p = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))

"""Embeddings.

The default backend is a deterministic local hash embedding: no network, no
key, no flakiness, and good enough for lexical-overlap retrieval in V1. A real
embedding model can be swapped in via ``EMBEDDING_BACKEND=llm`` without
touching the retrieval code.
"""

from __future__ import annotations

import hashlib
import math
import re
from itertools import pairwise
from typing import Protocol, runtime_checkable

_TOKEN = re.compile(r"[0-9A-Za-z_]+")


def _tokenize(text: str) -> list[str]:
    """Latin words plus CJK bigrams - enough signal for overlap scoring."""
    tokens = [t.lower() for t in _TOKEN.findall(text)]
    cjk = [ch for ch in text if 0x4E00 <= ord(ch) <= 0x9FFF]
    tokens += cjk
    tokens += ["".join(pair) for pair in pairwise(cjk)]
    return tokens


@runtime_checkable
class Embedder(Protocol):
    dimension: int

    async def embed(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Deterministic bag-of-tokens projection onto the unit sphere."""

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    def embed_sync(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]

    async def embed(self, text: str) -> list[float]:
        return self.embed_sync(text)


class LLMEmbedder:
    """Calls a hosted embedding endpoint; falls back to hashing on failure."""

    def __init__(self, client, model: str, dimension: int = 1536) -> None:
        self.client = client
        self.model = model
        self.dimension = dimension
        self._fallback = HashEmbedder(dimension)

    async def embed(self, text: str) -> list[float]:
        embed_fn = getattr(self.client, "embed", None)
        if embed_fn is None or not self.model:
            return self._fallback.embed_sync(text)
        try:
            vector = await embed_fn(self.model, text)
            return list(vector)
        except Exception:
            return self._fallback.embed_sync(text)


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def build_embedder(settings) -> Embedder:
    backend = (getattr(settings, "embedding_backend", "hash") or "hash").lower()
    dimension = int(getattr(settings, "embedding_dim", 256))
    if backend == "llm":
        return LLMEmbedder(None, getattr(settings, "embedding_model", ""), dimension)
    return HashEmbedder(dimension)

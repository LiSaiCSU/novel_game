"""LLM provider abstraction (Prompt section 3).

Business code never talks to a vendor SDK. It talks to this interface, and the
model name always arrives from configuration.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str = "user"
    content: str


@dataclass(slots=True)
class LLMRequest:
    model: str
    messages: list[LLMMessage]
    system: str | None = None
    temperature: float = 0.7
    max_output_tokens: int = 1024
    json_mode: bool = False
    stop: list[str] = field(default_factory=list)
    #: Vendor-specific keys merged into the request body verbatim. This is how
    #: things like a thinking-mode switch reach the endpoint without any vendor
    #: name appearing in engine code - it always comes from configuration.
    extra_body: dict[str, Any] = field(default_factory=dict)


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMResponse(BaseModel):
    text: str = ""
    model: str = ""
    provider: str = ""
    usage: LLMUsage = Field(default_factory=LLMUsage)
    latency_ms: int = 0
    finish_reason: str = "stop"
    raw: dict[str, Any] = Field(default_factory=dict)


class LLMCallRecord(BaseModel):
    """One row of the observability trail (Prompt sections 46, 60)."""

    role: str
    provider: str
    model: str
    prompt_version: str = ""
    temperature: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    attempts: int = 1
    repaired: bool = False
    valid: bool = True
    degraded: bool = False
    error: str | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def generate_text(self, request: LLMRequest) -> LLMResponse: ...
    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]: ...
    @property
    def available(self) -> bool: ...


class Stopwatch:
    __slots__ = ("_start",)

    def __init__(self) -> None:
        self._start = time.perf_counter()

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)


def estimate_tokens(text: str) -> int:
    """Cheap, provider-agnostic budget estimate.

    CJK text is roughly one token per character while Latin text is closer to
    four characters per token, so mixed prompts are counted separately.
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if 0x4E00 <= ord(ch) <= 0x9FFF)
    other = len(text) - cjk
    return cjk + max(1, other // 4)

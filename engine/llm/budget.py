"""Provider-neutral per-turn inference budget guard."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from engine.core.errors import LLMError
from engine.llm.provider import LLMRequest, LLMResponse, estimate_tokens


class BudgetedProvider:
    """Reject a call before dispatch when its reserved tokens exceed the turn cap."""

    def __init__(self, provider: Any, token_limit: int) -> None:
        self._provider = provider
        self._limit = max(0, token_limit)
        self._reserved = 0
        self.name = provider.name

    @property
    def available(self) -> bool:
        return self._provider.available

    def _reserve(self, request: LLMRequest) -> None:
        prompt = (request.system or "") + "".join(message.content for message in request.messages)
        requested = estimate_tokens(prompt) + request.max_output_tokens
        if self._limit and self._reserved + requested > self._limit:
            raise LLMError(
                "turn inference budget exhausted",
                limit=self._limit,
                reserved=self._reserved,
                requested=requested,
            )
        self._reserved += requested

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        self._reserve(request)
        return await self._provider.generate_text(request)

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        self._reserve(request)
        async for chunk in self._provider.stream_text(request):
            yield chunk

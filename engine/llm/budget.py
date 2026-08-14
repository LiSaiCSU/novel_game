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

    def _reserve(self, request: LLMRequest) -> int:
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
        return requested

    def _settle(self, reserved: int, actual: int) -> None:
        """Replace a worst-case reservation with the provider's real usage.

        A request has to fit before it is dispatched, but charging every role's
        maximum output forever made a healthy multi-stage turn exhaust its cap
        even when responses were short.  The cap now behaves like a normal
        reservation system: protect the in-flight call, then account for what
        it actually consumed.
        """
        self._reserved = max(0, self._reserved - reserved + max(0, actual))

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        reserved = self._reserve(request)
        try:
            response = await self._provider.generate_text(request)
        except Exception:
            # A rejected/failed HTTP request has no trustworthy usage value.
            # Keep the prompt estimate, which is conservative without charging
            # the entire unused output allowance.
            prompt = (request.system or "") + "".join(
                message.content for message in request.messages
            )
            self._settle(reserved, estimate_tokens(prompt))
            raise
        self._settle(reserved, response.usage.total)
        return response

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        reserved = self._reserve(request)
        chunks: list[str] = []
        try:
            async for chunk in self._provider.stream_text(request):
                chunks.append(chunk)
                yield chunk
        finally:
            prompt = (request.system or "") + "".join(
                message.content for message in request.messages
            )
            self._settle(
                reserved,
                estimate_tokens(prompt) + estimate_tokens("".join(chunks)),
            )

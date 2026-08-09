"""Concrete providers.

``NullProvider`` and ``ScriptedProvider`` are first-class citizens, not
afterthoughts: they are what let the entire world engine run and be tested
without a network call (DECISIONS D-007).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from engine.core.errors import LLMError, LLMTimeout
from engine.llm.provider import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    Stopwatch,
    estimate_tokens,
)


def _prompt_text(request: LLMRequest) -> str:
    parts = [request.system or ""] + [m.content for m in request.messages]
    return "\n".join(p for p in parts if p)


class NullProvider:
    """Refuses to generate. Callers must fall back to deterministic logic."""

    name = "null"

    @property
    def available(self) -> bool:
        return False

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        raise LLMError("no LLM provider configured", model=request.model)

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        raise LLMError("no LLM provider configured", model=request.model)
        yield ""  # pragma: no cover - keeps this an async generator


class ScriptedProvider:
    """Replays canned responses. Used by evals so they cost nothing and never flake."""

    name = "scripted"

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        *,
        default: str = "",
        strict: bool = False,
    ) -> None:
        self.responses = responses or {}
        self.default = default
        self.strict = strict
        self.calls: list[LLMRequest] = []

    @property
    def available(self) -> bool:
        return True

    def _lookup(self, request: LLMRequest) -> str:
        haystack = _prompt_text(request)
        for needle, response in self.responses.items():
            if needle in haystack:
                return response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
        if self.strict:
            raise LLMError("no scripted response matched", model=request.model)
        return self.default

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        watch = Stopwatch()
        text = self._lookup(request)
        return LLMResponse(
            text=text,
            model=request.model,
            provider=self.name,
            usage=LLMUsage(
                prompt_tokens=estimate_tokens(_prompt_text(request)),
                completion_tokens=estimate_tokens(text),
            ),
            latency_ms=watch.elapsed_ms,
        )

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        response = await self.generate_text(request)
        for chunk_start in range(0, len(response.text), 24):
            yield response.text[chunk_start : chunk_start + 24]


class _HTTPProviderBase:
    """Shared plumbing for HTTP-based vendors."""

    name = "http"

    def __init__(self, api_key: str, base_url: str, timeout: float = 60.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            raise LLMTimeout(f"{self.name} request timed out") from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            raise LLMError(
                f"{self.name} returned {exc.response.status_code}", body=body
            ) from exc
        except Exception as exc:
            raise LLMError(f"{self.name} request failed: {exc}") from exc


class AnthropicProvider(_HTTPProviderBase):
    name = "anthropic"
    DEFAULT_BASE_URL = "https://api.anthropic.com"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, base_url: str = "", timeout: float = 60.0) -> None:
        super().__init__(api_key, base_url or self.DEFAULT_BASE_URL, timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        watch = Stopwatch()
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        if request.system:
            payload["system"] = request.system
        if request.stop:
            payload["stop_sequences"] = request.stop

        data = await self._post(f"{self.base_url}/v1/messages", self._headers(), payload)
        blocks = data.get("content", []) or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        usage = data.get("usage", {}) or {}
        return LLMResponse(
            text=text,
            model=data.get("model", request.model),
            provider=self.name,
            usage=LLMUsage(
                prompt_tokens=int(usage.get("input_tokens", 0)),
                completion_tokens=int(usage.get("output_tokens", 0)),
            ),
            latency_ms=watch.elapsed_ms,
            finish_reason=str(data.get("stop_reason", "stop")),
        )

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        import httpx

        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "stream": True,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        if request.system:
            payload["system"] = request.system
        async with httpx.AsyncClient(timeout=self.timeout) as client, client.stream(
            "POST", f"{self.base_url}/v1/messages", headers=self._headers(), json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if not body or body == "[DONE]":
                    continue
                try:
                    event = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "content_block_delta":
                    piece = (event.get("delta") or {}).get("text", "")
                    if piece:
                        yield piece


class OpenAIProvider(_HTTPProviderBase):
    name = "openai"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(self, api_key: str, base_url: str = "", timeout: float = 60.0) -> None:
        super().__init__(api_key, base_url or self.DEFAULT_BASE_URL, timeout)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}

    def _payload(self, request: LLMRequest, stream: bool = False) -> dict[str, Any]:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.stop:
            payload["stop"] = request.stop
        if stream:
            payload["stream"] = True
        return payload

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        watch = Stopwatch()
        data = await self._post(
            f"{self.base_url}/chat/completions", self._headers(), self._payload(request)
        )
        choices = data.get("choices", []) or []
        text = (choices[0].get("message", {}) or {}).get("content", "") if choices else ""
        usage = data.get("usage", {}) or {}
        return LLMResponse(
            text=text or "",
            model=data.get("model", request.model),
            provider=self.name,
            usage=LLMUsage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ),
            latency_ms=watch.elapsed_ms,
            finish_reason=str(choices[0].get("finish_reason", "stop")) if choices else "stop",
        )

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client, client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=self._payload(request, stream=True),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if not body or body == "[DONE]":
                    continue
                try:
                    event = json.loads(body)
                except json.JSONDecodeError:
                    continue
                for choice in event.get("choices", []):
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield piece


class CompatibleProvider(OpenAIProvider):
    """Any OpenAI-compatible endpoint: self-hosted, gateway, or another vendor."""

    name = "compatible"

    def __init__(self, api_key: str, base_url: str, timeout: float = 60.0) -> None:
        if not base_url:
            raise LLMError("COMPATIBLE_BASE_URL must be set for the compatible provider")
        _HTTPProviderBase.__init__(self, api_key, base_url, timeout)

    @property
    def available(self) -> bool:
        return bool(self.base_url)


def build_provider(settings: Any) -> Any:
    """Factory driven purely by configuration."""
    kind = (getattr(settings, "llm_provider", "null") or "null").lower()
    timeout = float(getattr(settings, "llm_timeout_seconds", 60.0))
    if kind == "anthropic":
        return AnthropicProvider(
            settings.anthropic_api_key, settings.anthropic_base_url, timeout
        )
    if kind == "openai":
        return OpenAIProvider(settings.openai_api_key, settings.openai_base_url, timeout)
    if kind == "compatible":
        return CompatibleProvider(
            settings.compatible_api_key, settings.compatible_base_url, timeout
        )
    if kind == "scripted":
        return ScriptedProvider()
    return NullProvider()


async def with_timeout(coro, seconds: float):
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except TimeoutError as exc:
        raise LLMTimeout(f"LLM call exceeded {seconds}s") from exc

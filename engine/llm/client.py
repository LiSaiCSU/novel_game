"""LLMClient - the single entry point every AI subsystem uses.

Responsibilities: pick the model, render the versioned prompt, call the
provider, coerce the answer into a schema, retry with a repair instruction,
and record exactly what happened.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel

from engine.core.errors import LLMError, StructuredOutputError
from engine.core.logging import get_logger
from engine.core.types import LLMRole
from engine.llm.provider import (
    LLMCallRecord,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    estimate_tokens,
)
from engine.llm.router import ModelChoice, ModelRouter
from engine.llm.structured import parse_structured, repair_instruction, schema_hint

T = TypeVar("T", bound=BaseModel)
logger = get_logger("llm")


class LLMClient:
    def __init__(
        self,
        provider: Any,
        router: ModelRouter,
        registry: Any,
        *,
        max_retries: int = 1,
        max_repairs: int = 2,
    ) -> None:
        self.provider = provider
        self.router = router
        self.registry = registry
        self.max_retries = max_retries
        self.max_repairs = max_repairs
        self.records: list[LLMCallRecord] = []

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return bool(getattr(self.provider, "available", False))

    def usable_for(self, role: LLMRole) -> bool:
        """A role is usable only if both a provider and a model name exist."""
        return self.available and self.router.choose(role).configured

    def reset_records(self) -> None:
        self.records = []

    def total_usage(self) -> LLMUsage:
        return LLMUsage(
            prompt_tokens=sum(r.prompt_tokens for r in self.records),
            completion_tokens=sum(r.completion_tokens for r in self.records),
        )

    # ------------------------------------------------------------------
    async def generate_text(
        self,
        role: LLMRole,
        prompt: str,
        *,
        system: str | None = None,
        prompt_version: str = "",
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        choice = self.router.choose(
            role, temperature=temperature, max_output_tokens=max_output_tokens
        )
        self._require(choice)
        request = LLMRequest(
            model=choice.model,
            messages=[LLMMessage(role="user", content=prompt)],
            system=system,
            temperature=choice.temperature,
            max_output_tokens=choice.max_output_tokens,
        )
        response = await self._call(request, role, prompt_version, attempts=1)
        return response

    async def stream_text(
        self,
        role: LLMRole,
        prompt: str,
        *,
        system: str | None = None,
        prompt_version: str = "",
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        choice = self.router.choose(
            role, temperature=temperature, max_output_tokens=max_output_tokens
        )
        self._require(choice)
        request = LLMRequest(
            model=choice.model,
            messages=[LLMMessage(role="user", content=prompt)],
            system=system,
            temperature=choice.temperature,
            max_output_tokens=choice.max_output_tokens,
        )
        collected: list[str] = []
        async for chunk in self.provider.stream_text(request):
            collected.append(chunk)
            yield chunk
        text = "".join(collected)
        self.records.append(
            LLMCallRecord(
                role=str(role),
                provider=getattr(self.provider, "name", "unknown"),
                model=choice.model,
                prompt_version=prompt_version,
                temperature=choice.temperature,
                prompt_tokens=estimate_tokens(prompt),
                completion_tokens=estimate_tokens(text),
                attempts=1,
                valid=True,
            )
        )

    async def generate_structured(
        self,
        role: LLMRole,
        schema: type[T],
        prompt: str,
        *,
        system: str | None = None,
        prompt_version: str = "",
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> T:
        """Validate-or-repair loop. Raises StructuredOutputError when exhausted."""
        choice = self.router.choose(
            role, temperature=temperature, max_output_tokens=max_output_tokens
        )
        self._require(choice)

        messages = [LLMMessage(role="user", content=prompt)]
        last_error = "unknown"
        last_raw = ""
        attempts = 0

        for attempt in range(self.max_repairs + 1):
            attempts = attempt + 1
            request = LLMRequest(
                model=choice.model,
                messages=list(messages),
                system=system,
                temperature=choice.temperature,
                max_output_tokens=choice.max_output_tokens,
                json_mode=True,
            )
            try:
                response = await self._call(
                    request, role, prompt_version, attempts=attempts, record=False
                )
            except LLMError as exc:
                last_error, last_raw = str(exc), ""
                if attempt >= self.max_retries:
                    break
                continue

            last_raw = response.text
            try:
                parsed = parse_structured(schema, response.text)
            except StructuredOutputError as exc:
                last_error = exc.message
                logger.warning(
                    "structured output rejected (role=%s attempt=%s): %s",
                    role,
                    attempts,
                    last_error,
                )
                messages.append(LLMMessage(role="assistant", content=response.text[:1500]))
                messages.append(
                    LLMMessage(
                        role="user", content=repair_instruction(schema, last_error, response.text)
                    )
                )
                continue

            self.records.append(
                LLMCallRecord(
                    role=str(role),
                    provider=getattr(self.provider, "name", "unknown"),
                    model=choice.model,
                    prompt_version=prompt_version,
                    temperature=choice.temperature,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    latency_ms=response.latency_ms,
                    attempts=attempts,
                    repaired=attempts > 1,
                    valid=True,
                )
            )
            return parsed

        self.records.append(
            LLMCallRecord(
                role=str(role),
                provider=getattr(self.provider, "name", "unknown"),
                model=choice.model,
                prompt_version=prompt_version,
                temperature=choice.temperature,
                attempts=attempts,
                repaired=attempts > 1,
                valid=False,
                error=last_error,
            )
        )
        raise StructuredOutputError(
            f"could not obtain valid {schema.__name__} after {attempts} attempts: {last_error}",
            attempts=attempts,
            raw=last_raw,
        )

    # ------------------------------------------------------------------
    def _require(self, choice: ModelChoice) -> None:
        if not self.available:
            raise LLMError("no LLM provider is configured", role=str(choice.role))
        if not choice.configured:
            raise LLMError(
                f"no model configured for role {choice.role}; set it in .env",
                role=str(choice.role),
            )

    async def _call(
        self,
        request: LLMRequest,
        role: LLMRole,
        prompt_version: str,
        *,
        attempts: int,
        record: bool = True,
    ) -> LLMResponse:
        response = await self.provider.generate_text(request)
        if record:
            self.records.append(
                LLMCallRecord(
                    role=str(role),
                    provider=getattr(self.provider, "name", "unknown"),
                    model=request.model,
                    prompt_version=prompt_version,
                    temperature=request.temperature,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    latency_ms=response.latency_ms,
                    attempts=attempts,
                    valid=True,
                )
            )
        return response

    def record_degraded(self, role: LLMRole, reason: str) -> None:
        """Note that a subsystem fell back to deterministic logic."""
        self.records.append(
            LLMCallRecord(
                role=str(role),
                provider=getattr(self.provider, "name", "unknown"),
                model="",
                valid=False,
                degraded=True,
                error=reason,
            )
        )

    def schema_hint(self, schema: type[BaseModel]) -> str:
        return schema_hint(schema)

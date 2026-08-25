"""Route one logical model across several independently configured endpoints.

A deployment usually has more than one way to reach a model: a primary vendor,
a cheaper gateway, a spare key. ``ProviderPool`` already spreads load across
equivalent credentials, but it cannot help when an endpoint is *broken* — it
round-robins straight into the failure. This module adds the other half: an
ordered chain that moves to the next endpoint when one errors, and a per-target
model map so each endpoint can name the same capability differently.

Streaming needs care. Once a chunk has been handed to the caller the turn is
already partly rendered, so switching endpoints mid-answer would splice two
different continuations together. A stream therefore only fails over while it
has produced nothing.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from engine.core.errors import LLMError
from engine.llm.provider import LLMRequest, LLMResponse

logger = logging.getLogger("aiworld.llm.failover")


@dataclass(slots=True)
class FailoverTarget:
    """One endpoint, plus the model names it uses for each engine role."""

    provider: Any
    name: str = ""
    #: role -> model name. A role that is absent falls back to ``default_model``.
    models: dict[str, str] = field(default_factory=dict)
    default_model: str = ""
    extra_body: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(getattr(self.provider, "available", False))

    def prepare(self, request: LLMRequest) -> LLMRequest:
        """Rewrite a request for this endpoint's own vocabulary."""

        model = self.models.get(request.role) or self.default_model or request.model
        extra_body = dict(request.extra_body)
        if self.extra_body:
            extra_body = {**self.extra_body, **extra_body}
        return replace(request, model=model, extra_body=extra_body)


class FailoverProvider:
    """Try each target in order and surface the last error if all of them fail."""

    name = "failover"

    def __init__(
        self,
        targets: list[FailoverTarget],
        *,
        on_result: Callable[[str, bool, str], None] | None = None,
    ) -> None:
        if not targets:
            raise ValueError("FailoverProvider requires at least one target")
        self.targets = targets
        self.name = f"failover({len(targets)})"
        # Lets the caller record health without this module importing a database.
        self._on_result = on_result

    @property
    def available(self) -> bool:
        return any(target.available for target in self.targets)

    def _usable(self) -> list[FailoverTarget]:
        usable = [target for target in self.targets if target.available]
        # Every target being unavailable is itself a configuration error worth
        # reporting through the normal call path rather than an empty result.
        return usable or self.targets[:1]

    def _record(self, target: FailoverTarget, ok: bool, detail: str = "") -> None:
        if self._on_result is None:
            return
        try:
            self._on_result(target.name, ok, detail)
        except Exception:  # pragma: no cover - health tracking must never break a turn
            logger.warning("failover health callback failed for %s", target.name)

    async def generate_text(self, request: LLMRequest) -> LLMResponse:
        targets = self._usable()
        last: Exception | None = None
        for index, target in enumerate(targets):
            try:
                response = await target.provider.generate_text(target.prepare(request))
            except Exception as exc:
                last = exc
                self._record(target, False, type(exc).__name__)
                logger.warning(
                    "endpoint %s failed for role=%s (%s of %s): %s",
                    target.name or index,
                    request.role or "?",
                    index + 1,
                    len(targets),
                    type(exc).__name__,
                )
                continue
            self._record(target, True)
            return response
        raise LLMError(
            f"every configured endpoint failed for role {request.role or 'unknown'}"
        ) from last

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        targets = self._usable()
        last: Exception | None = None
        for index, target in enumerate(targets):
            produced = False
            try:
                async for chunk in target.provider.stream_text(target.prepare(request)):
                    produced = True
                    yield chunk
            except Exception as exc:
                last = exc
                self._record(target, False, type(exc).__name__)
                if produced:
                    # Half a scene has already reached the player. Restarting on
                    # another endpoint would continue from a different draft, so
                    # let the caller handle a truncated turn instead.
                    logger.warning(
                        "endpoint %s failed mid-stream for role=%s; not failing over",
                        target.name or index,
                        request.role or "?",
                    )
                    raise
                logger.warning(
                    "endpoint %s failed before streaming for role=%s (%s of %s): %s",
                    target.name or index,
                    request.role or "?",
                    index + 1,
                    len(targets),
                    type(exc).__name__,
                )
                continue
            self._record(target, True)
            return
        raise LLMError(
            f"every configured endpoint failed for role {request.role or 'unknown'}"
        ) from last

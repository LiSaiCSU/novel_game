"""Engine exception hierarchy."""

from __future__ import annotations

from typing import Any


class EngineError(Exception):
    """Base class for every engine-originated failure."""

    code: str = "ENGINE_ERROR"

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "context": self.context}


class ContentPackError(EngineError):
    code = "CONTENT_PACK_ERROR"


class ContentValidationError(ContentPackError):
    code = "CONTENT_VALIDATION_ERROR"


class RuleViolation(EngineError):
    """A deterministic rule rejected the action. Not a bug - a game outcome."""

    code = "RULE_VIOLATION"

    def __init__(self, reason_code: str, message: str, **context: Any) -> None:
        super().__init__(message, **context)
        self.reason_code = reason_code

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["reason_code"] = self.reason_code
        return data


class ConsistencyViolation(EngineError):
    """The world was about to enter an impossible state. Always an engine bug."""

    code = "CONSISTENCY_VIOLATION"

    def __init__(self, check: str, message: str, **context: Any) -> None:
        super().__init__(message, **context)
        self.check = check

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["check"] = self.check
        return data


class ProposalRejected(EngineError):
    """An AI proposal failed semantic validation and was discarded."""

    code = "PROPOSAL_REJECTED"

    def __init__(self, source: str, message: str, **context: Any) -> None:
        super().__init__(message, **context)
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["source"] = self.source
        return data


class LLMError(EngineError):
    code = "LLM_ERROR"


class LLMTimeout(LLMError):
    code = "LLM_TIMEOUT"


class LLMTruncated(LLMError):
    """The model hit its output budget before producing any usable content.

    Reasoning models spend the same budget on hidden thought, so a request that
    is generous for a plain model can come back completely empty. The caller is
    expected to retry with a larger budget rather than degrade to templates.
    """

    code = "LLM_TRUNCATED"

    def __init__(self, message: str, budget: int = 0, **context: Any) -> None:
        super().__init__(message, **context)
        self.budget = budget


class StructuredOutputError(LLMError):
    """The model could not be coerced into the requested schema."""

    code = "STRUCTURED_OUTPUT_ERROR"

    def __init__(self, message: str, attempts: int = 0, raw: str = "", **context: Any) -> None:
        super().__init__(message, **context)
        self.attempts = attempts
        self.raw = raw


class PromptRenderError(EngineError):
    code = "PROMPT_RENDER_ERROR"


class NotFoundError(EngineError):
    code = "NOT_FOUND"


class ConcurrencyError(EngineError):
    code = "CONCURRENCY_ERROR"

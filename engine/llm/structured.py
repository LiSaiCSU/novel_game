"""Structured output with repair (Prompt section 47).

A model returning JSON is not evidence that the JSON is correct. Nothing
reaches the world database until it has survived schema validation here and
semantic validation downstream.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from engine.core.errors import StructuredOutputError

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Pull a JSON value out of a model response that may be noisy."""
    if not text or not text.strip():
        raise StructuredOutputError("empty model response", raw=text or "")

    candidates: list[str] = []
    stripped = text.strip()
    candidates.append(stripped)
    for match in _FENCE.findall(text):
        candidates.append(match.strip())
    # Fall back to the outermost balanced braces or brackets.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise StructuredOutputError("no parseable JSON in model response", raw=text[:1500])


def validate_into(schema: type[T], payload: Any) -> T:
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise StructuredOutputError(
            f"response did not match {schema.__name__}: {exc.errors()[:3]}",
            raw=json.dumps(payload, ensure_ascii=False)[:1500],
        ) from exc


def parse_structured(schema: type[T], text: str) -> T:
    return validate_into(schema, extract_json(text))


def schema_hint(schema: type[BaseModel]) -> str:
    """A compact JSON Schema to paste into a prompt."""
    return json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)

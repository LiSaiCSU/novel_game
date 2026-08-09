"""Prompt loading and versioning (Prompt section 46).

Prompts are files, not string literals in Python. Every call records which
version it used so A/B comparisons are possible after the fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from engine.core.errors import PromptRenderError

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

COMMON_CONSTRAINTS = "_common_constraints"


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    role: str
    version: str
    body: str
    meta: dict[str, Any]

    @property
    def temperature(self) -> float | None:
        value = self.meta.get("temperature")
        return float(value) if value is not None else None

    @property
    def max_output_tokens(self) -> int | None:
        value = self.meta.get("max_output_tokens")
        return int(value) if value is not None else None

    def placeholders(self) -> set[str]:
        return set(_PLACEHOLDER.findall(self.body))

    def render(self, **variables: Any) -> str:
        missing = self.placeholders() - set(variables)
        if missing:
            raise PromptRenderError(
                f"prompt {self.role}/{self.version} is missing variables: {sorted(missing)}",
                role=self.role,
                version=self.version,
                missing=sorted(missing),
            )

        def substitute(match: re.Match[str]) -> str:
            value = variables[match.group(1)]
            return value if isinstance(value, str) else str(value)

        return _PLACEHOLDER.sub(substitute, self.body)


class PromptRegistry:
    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self._cache: dict[tuple[str, str], PromptTemplate] = {}

    def _path(self, role: str, version: str) -> Path:
        if role == COMMON_CONSTRAINTS:
            return self.directory / f"{role}.md"
        return self.directory / f"{role}_{version}.md"

    def get(self, role: str, version: str = "v1") -> PromptTemplate:
        key = (role, version)
        if key in self._cache:
            return self._cache[key]
        path = self._path(role, version)
        if not path.exists():
            raise PromptRenderError(f"prompt file not found: {path}", role=role, version=version)
        raw = path.read_text(encoding="utf-8")
        meta: dict[str, Any] = {}
        match = _FRONT_MATTER.match(raw)
        body = raw
        if match:
            meta = yaml.safe_load(match.group(1)) or {}
            body = raw[match.end() :]
        template = PromptTemplate(role=role, version=version, body=body.strip(), meta=meta)
        self._cache[key] = template
        return template

    def common_constraints(self) -> str:
        try:
            return self.get(COMMON_CONSTRAINTS, "v1").body
        except PromptRenderError:
            return ""

    def render(self, role: str, version: str = "v1", **variables: Any) -> str:
        template = self.get(role, version)
        if "common_constraints" in template.placeholders():
            variables.setdefault("common_constraints", self.common_constraints())
        return template.render(**variables)

    def available(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for path in sorted(self.directory.glob("*.md")):
            stem = path.stem
            if stem.startswith("_"):
                continue
            role, _, version = stem.rpartition("_")
            if role and version.startswith("v"):
                out.append((role, version))
        return out


@lru_cache(maxsize=4)
def get_registry(directory: str) -> PromptRegistry:
    return PromptRegistry(directory)

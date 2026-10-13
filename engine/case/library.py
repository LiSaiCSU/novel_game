"""Loads authored cases from ``content/cases``. Cases are code-reviewed content."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from engine.case.schema import CaseDefinition


@lru_cache(maxsize=4)
def load_cases(directory: str) -> dict[str, CaseDefinition]:
    root = Path(directory)
    cases: dict[str, CaseDefinition] = {}
    if not root.is_dir():
        return cases
    for path in sorted(root.glob("*.yaml")):
        with path.open(encoding="utf-8") as handle:
            case = CaseDefinition.model_validate(yaml.safe_load(handle))
        if case.key in cases:
            raise ValueError(f"duplicate case key {case.key}")
        cases[case.key] = case
    return cases

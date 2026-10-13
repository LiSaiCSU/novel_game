"""Mutable per-run state of a case. Persisted as JSON; never sent to clients raw."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

LogKind = Literal[
    "narration",
    "npc",
    "player",
    "evidence",
    "break",
    "fail",
    "event",
    "note",
    "system",
    "verdict",
]


class LogEntry(BaseModel):
    id: int
    kind: LogKind
    text: str
    speaker: str | None = None
    evidence: str | None = None
    minutes_left: int


class CaseState(BaseModel):
    case_key: str
    case_version: int
    seed: str
    minutes_left: int
    status: Literal["briefing", "active", "deadline", "closed"] = "briefing"
    current: str | None = None
    evidence: list[str] = Field(default_factory=list)
    examined: list[str] = Field(default_factory=list)
    statements: list[str] = Field(default_factory=list)
    broken: list[str] = Field(default_factory=list)
    used_options: list[str] = Field(default_factory=list)
    patience: dict[str, int] = Field(default_factory=dict)
    #: Hidden facts rolled for this run. Never sent to the client.
    variables: dict[str, str] = Field(default_factory=dict)
    stance: dict[str, int] = Field(default_factory=dict)
    silent: list[str] = Field(default_factory=list)
    met: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    fired_events: list[str] = Field(default_factory=list)
    wrong_presents: dict[str, int] = Field(default_factory=dict)
    moves: int = 0
    log: list[LogEntry] = Field(default_factory=list)
    result: dict[str, Any] | None = None

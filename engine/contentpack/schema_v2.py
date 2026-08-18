"""Versioned, author-facing content package contracts.

The runtime still understands the original bundled YAML layout while projects
are migrated.  These models are the stable public boundary used by the creator
API, compiler and immutable releases.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from engine.contentpack.declarative import DeclarativeRule, validate_expression_structure

SCHEMA_VERSION: Literal["2.0"] = "2.0"
ENGINE_API_VERSION = "2"
ENGINE_VERSION = "0.2.0"
_KEY = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
_ASSERTION_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EngineCompatibility(StrictModel):
    api_version: str = ENGINE_API_VERSION
    min_version: str = "0.2.0"
    max_version: str | None = None


class PlayerField(StrictModel):
    key: str
    label: str
    type: Literal["text", "integer", "choice", "tags"] = "text"
    required: bool = False
    default: str | int | list[str] | None = None
    minimum: int | None = None
    maximum: int | None = None
    choices: list[dict[str, str]] = Field(default_factory=list)
    binding: Literal["property", "attribute", "resource", "progression"] = "property"

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not _KEY.fullmatch(value):
            raise ValueError("must be a stable snake_case key")
        return value


class ThemeDefinition(StrictModel):
    accent: str = "#7c6aa6"
    background: str = "#f7f4ef"
    surface: str = "#ffffff"
    text: str = "#25222b"
    heading_font: str = "serif"
    body_font: str = "sans-serif"


class AssetReference(StrictModel):
    key: str
    kind: Literal["cover", "avatar", "background"]
    path: str
    alt: str

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not _KEY.fullmatch(value):
            raise ValueError("must be a stable snake_case key")
        return value

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("asset path must stay inside the package")
        return normalized


class ContentManifestV2(StrictModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    key: str
    slug: str
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=1000)
    version: str = "1.0.0"
    locale: str = "zh-CN"
    rating: Literal["all", "13+", "16+", "18+"] = "16+"
    tags: list[str] = Field(default_factory=list, max_length=12)
    engine: EngineCompatibility = Field(default_factory=EngineCompatibility)
    entry_scenario: str
    player_fields: list[PlayerField] = Field(default_factory=list)
    # Lists are used instead of sets because a Release checksum must be stable
    # across interpreter processes (set iteration order is hash-randomized).
    capabilities: list[str] = Field(default_factory=list)
    theme: ThemeDefinition = Field(default_factory=ThemeDefinition)
    assets: list[AssetReference] = Field(default_factory=list)
    trusted_rule_plugin: str | None = None

    @field_validator("key", "entry_scenario")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not _KEY.fullmatch(value):
            raise ValueError("must be a stable snake_case key")
        return value

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("must be a lowercase URL slug")
        return value

    @field_validator("capabilities")
    @classmethod
    def stable_capabilities(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


class ResourceDefinition(StrictModel):
    key: str
    label: str
    minimum: float = 0
    maximum: float = 100
    default: float = 0

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not _KEY.fullmatch(value):
            raise ValueError("must be a stable snake_case key")
        return value

    @model_validator(mode="after")
    def valid_range(self) -> ResourceDefinition:
        if self.minimum > self.default or self.default > self.maximum:
            raise ValueError("resource default must be inside its range")
        return self


class ProgressionTier(StrictModel):
    key: str
    label: str
    order: int = Field(ge=0)

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not _KEY.fullmatch(value):
            raise ValueError("must be a stable snake_case key")
        return value


class ProgressionDefinition(StrictModel):
    key: str
    label: str
    tiers: list[ProgressionTier] = Field(min_length=1)

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not _KEY.fullmatch(value):
            raise ValueError("must be a stable snake_case key")
        return value

    @model_validator(mode="after")
    def unique_tiers(self) -> ProgressionDefinition:
        keys = [tier.key for tier in self.tiers]
        orders = [tier.order for tier in self.tiers]
        if len(keys) != len(set(keys)) or len(orders) != len(set(orders)):
            raise ValueError("progression tier keys and orders must be unique")
        return self


class ScenarioDefinition(StrictModel):
    key: str
    title: str
    premise: str = ""
    start_location: str
    player_template: dict[str, Any] = Field(default_factory=dict)
    initial_threads: list[str] = Field(default_factory=list)


class EndingDefinition(StrictModel):
    key: str
    title: str = Field(min_length=1, max_length=120)
    type: Literal["romance", "bond", "independent", "other"] = "other"
    lead: str | None = None
    condition: Any = False
    requires_consent: bool = False
    hidden_until_available: bool = True
    priority: int = Field(default=0, ge=0, le=1000)
    epilogue: str = Field(min_length=1, max_length=4000)

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not _KEY.fullmatch(value):
            raise ValueError("must be a stable snake_case key")
        return value

    @field_validator("condition")
    @classmethod
    def condition_is_bounded(cls, value: Any) -> Any:
        validate_expression_structure(value)
        return value

    @model_validator(mode="after")
    def romance_is_explicit(self) -> EndingDefinition:
        if self.type == "romance" and not self.lead:
            raise ValueError("romance ending requires a lead")
        if self.type == "romance" and not self.requires_consent:
            raise ValueError("romance ending must require explicit consent")
        return self


class AuthorTestPlayer(StrictModel):
    name: str = Field(default="Test Player", min_length=1, max_length=80)
    age: int = Field(default=20, ge=18, le=120)
    gender: str = Field(default="unspecified", max_length=40)
    background: str = Field(default="", max_length=1000)
    attributes: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    progressions: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)


class AuthorRelationshipFixture(StrictModel):
    affection: int | None = Field(default=None, ge=-100, le=100)
    trust: int | None = Field(default=None, ge=-100, le=100)
    respect: int | None = Field(default=None, ge=-100, le=100)
    fear: int | None = Field(default=None, ge=0, le=100)
    hatred: int | None = Field(default=None, ge=0, le=100)
    suspicion: int | None = Field(default=None, ge=0, le=100)
    dependency: int | None = Field(default=None, ge=0, le=100)
    familiarity: int | None = Field(default=None, ge=0, le=100)
    boundaries: int | None = Field(default=None, ge=0, le=100)
    tags: list[str] = Field(default_factory=list, max_length=20)


class AuthorThreadFixture(StrictModel):
    status: Literal["dormant", "active", "resolved", "failed", "abandoned"] | None = None
    stage: int | None = Field(default=None, ge=0, le=10_000)


class AuthorTestFixtures(StrictModel):
    relationships: dict[str, AuthorRelationshipFixture] = Field(default_factory=dict)
    knowledge: dict[
        str,
        dict[str, Literal["UNKNOWN", "HEARD", "SUSPECTED", "BELIEVED", "KNOWN", "DISBELIEVED"]],
    ] = Field(default_factory=dict)
    quests: dict[
        str,
        Literal[
            "offered", "active", "completed", "failed", "expired", "taken_by_other", "rejected"
        ],
    ] = Field(default_factory=dict)
    plot_threads: dict[str, AuthorThreadFixture] = Field(default_factory=dict)


class AuthorTestAction(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    narrative_max_chars: int = Field(default=800, ge=400, le=2000)


class AuthorAssertion(StrictModel):
    path: str
    op: Literal[
        "eq", "ne", "gt", "gte", "lt", "lte", "contains", "not_contains", "exists", "not_exists"
    ] = "eq"
    expected: Any = None

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        if len(value) > 240 or not _ASSERTION_PATH.fullmatch(value):
            raise ValueError("must be a bounded dotted snake_case path")
        return value


class AuthorTestCase(StrictModel):
    key: str
    name: str = Field(min_length=1, max_length=120)
    scenario: str | None = None
    player: AuthorTestPlayer = Field(default_factory=AuthorTestPlayer)
    fixtures: AuthorTestFixtures = Field(default_factory=AuthorTestFixtures)
    actions: list[AuthorTestAction] = Field(default_factory=list, max_length=20)
    assertions: list[AuthorAssertion] = Field(min_length=1, max_length=100)

    @field_validator("key", "scenario")
    @classmethod
    def valid_key(cls, value: str | None) -> str | None:
        if value is not None and not _KEY.fullmatch(value):
            raise ValueError("must be a stable snake_case key")
        return value


class ContentDocumentV2(StrictModel):
    """The normalized document graph compiled into a release artifact."""

    world: dict[str, Any]
    story: dict[str, Any] = Field(default_factory=dict)
    endings: list[EndingDefinition] = Field(default_factory=list)
    scenarios: list[ScenarioDefinition]
    locations: list[dict[str, Any]] = Field(default_factory=list)
    organizations: list[dict[str, Any]] = Field(default_factory=list)
    characters: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    abilities: list[dict[str, Any]] = Field(default_factory=list)
    quests: list[dict[str, Any]] = Field(default_factory=list)
    plot_threads: list[dict[str, Any]] = Field(default_factory=list)
    #: Visible pressure attached to those threads. Optional so packages
    #: published before clocks existed still validate.
    clocks: list[dict[str, Any]] = Field(default_factory=list)
    event_templates: list[dict[str, Any]] = Field(default_factory=list)
    offline_templates: list[dict[str, Any]] = Field(default_factory=list)
    npc_templates: dict[str, Any] = Field(default_factory=dict)
    engine_rules: dict[str, Any] = Field(default_factory=dict)
    calendar: dict[str, Any] = Field(default_factory=dict)
    narrative: dict[str, Any] = Field(default_factory=dict)
    vocabulary: dict[str, Any] = Field(default_factory=dict)
    attributes: list[dict[str, Any]] = Field(default_factory=list)
    resources: list[ResourceDefinition] = Field(default_factory=list)
    progressions: list[ProgressionDefinition] = Field(default_factory=list)
    rules: list[DeclarativeRule] = Field(default_factory=list)


class ContentPackageV2(StrictModel):
    manifest: ContentManifestV2
    content: ContentDocumentV2
    author_tests: list[AuthorTestCase] = Field(default_factory=list, max_length=64)


class CompiledRelease(StrictModel):
    manifest: ContentManifestV2
    content: ContentDocumentV2
    author_tests: list[AuthorTestCase] = Field(default_factory=list)
    checksum: str
    compiled_at: str
    compiler_version: str = "2.0.0"

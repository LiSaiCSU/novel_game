"""ContentPack: everything the engine knows about a particular world genre.

Swap the directory, get a different game. The engine itself contains no lore,
no realm names, no faction names and no Chinese strings (DECISIONS D-004).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from engine.contentpack.realms import RealmLadder
from engine.core.errors import ContentPackError, ContentValidationError

if TYPE_CHECKING:
    from engine.rules.plugin import RulePlugin

_FILES = {
    "pack": "pack.yaml",
    "calendar": "calendar.yaml",
    "realms": "realms.yaml",
    "rules": "rules.yaml",
    "locations": "locations.yaml",
    "factions": "factions.yaml",
    "characters": "characters.yaml",
    "npc_templates": "npc_templates.yaml",
    "items": "items.yaml",
    "skills": "skills.yaml",
    "facts": "facts.yaml",
    "plot_threads": "plot_threads.yaml",
    "event_templates": "event_templates.yaml",
    "narrative_templates": "narrative_templates.yaml",
}

_OPTIONAL = {"narrative_templates", "npc_templates", "event_templates"}


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ContentValidationError(f"{path.name} must contain a mapping at the top level")
    return data


@dataclass(slots=True)
class ContentPack:
    key: str
    root: Path
    meta: dict[str, Any]
    calendar: dict[str, Any]
    realms: RealmLadder
    rules: dict[str, Any]
    locations: list[dict[str, Any]]
    location_types: list[dict[str, Any]]
    factions: list[dict[str, Any]]
    characters: list[dict[str, Any]]
    seed_relationships: list[dict[str, Any]]
    npc_templates: dict[str, Any]
    items: list[dict[str, Any]]
    item_types: list[dict[str, Any]]
    rarities: list[dict[str, Any]]
    skills: list[dict[str, Any]]
    facts: list[dict[str, Any]]
    plot_threads: list[dict[str, Any]]
    quests: list[dict[str, Any]]
    event_types: list[dict[str, Any]]
    offline_templates: list[dict[str, Any]]
    narrative_templates: dict[str, Any] = field(default_factory=dict)
    rule_plugin: RulePlugin | None = None

    # -- convenience --------------------------------------------------------
    @property
    def name(self) -> str:
        return str(self.meta.get("name", self.key))

    @property
    def world_meta(self) -> dict[str, Any]:
        return dict(self.meta.get("world", {}))

    @property
    def narrative_style(self) -> dict[str, Any]:
        return dict(self.meta.get("narrative_style", {}))

    @property
    def vocabulary(self) -> dict[str, Any]:
        return dict(self.meta.get("vocabulary", {}))

    def rule(self, dotted_path: str, default: Any = None) -> Any:
        """``pack.rule("combat.hit_chance.base")``."""
        node: Any = self.rules
        for part in dotted_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def location(self, key: str) -> dict[str, Any] | None:
        return next((loc for loc in self.locations if loc.get("key") == key), None)

    def character(self, key: str) -> dict[str, Any] | None:
        return next((c for c in self.characters if c.get("key") == key), None)

    def item(self, key: str) -> dict[str, Any] | None:
        return next((i for i in self.items if i.get("key") == key), None)

    def skill(self, key: str) -> dict[str, Any] | None:
        return next((s for s in self.skills if s.get("key") == key), None)

    def fact(self, key: str) -> dict[str, Any] | None:
        return next((f for f in self.facts if f.get("key") == key), None)

    def event_type(self, key: str) -> dict[str, Any] | None:
        return next((e for e in self.event_types if e.get("key") == key), None)

    def event_importance(self, event_type: str, default: float = 0.1) -> float:
        entry = self.event_type(event_type)
        return float(entry.get("importance", default)) if entry else default

    def event_visibility(self, event_type: str, default: str = "LOCAL") -> str:
        entry = self.event_type(event_type)
        return str(entry.get("visibility", default)) if entry else default


def load_content_pack(content_dir: Path | str, pack_key: str) -> ContentPack:
    root = Path(content_dir) / pack_key
    if not root.is_dir():
        raise ContentPackError(f"content pack directory not found: {root}")

    raw: dict[str, dict[str, Any]] = {}
    for name, filename in _FILES.items():
        path = root / filename
        if not path.exists():
            if name in _OPTIONAL:
                raw[name] = {}
                continue
            raise ContentPackError(f"content pack {pack_key!r} is missing {filename}")
        raw[name] = _load_yaml(path)

    from engine.contentpack.plugin_loader import load_rule_plugin

    pack = ContentPack(
        key=pack_key,
        root=root,
        meta=raw["pack"],
        calendar=raw["calendar"],
        realms=RealmLadder(raw["realms"]),
        rules=raw["rules"],
        locations=list(raw["locations"].get("locations", [])),
        location_types=list(raw["locations"].get("location_types", [])),
        factions=list(raw["factions"].get("factions", [])),
        characters=list(raw["characters"].get("characters", [])),
        seed_relationships=list(raw["characters"].get("relationships", [])),
        npc_templates=raw["npc_templates"],
        items=list(raw["items"].get("items", [])),
        item_types=list(raw["items"].get("item_types", [])),
        rarities=list(raw["items"].get("rarities", [])),
        skills=list(raw["skills"].get("skills", [])),
        facts=list(raw["facts"].get("facts", [])),
        plot_threads=list(raw["plot_threads"].get("plot_threads", [])),
        quests=list(raw["plot_threads"].get("quests", [])),
        event_types=list(raw["event_templates"].get("event_types", [])),
        offline_templates=list(raw["event_templates"].get("offline_templates", [])),
        narrative_templates=raw["narrative_templates"],
        rule_plugin=load_rule_plugin(root, raw["pack"]),
    )
    validate_content_pack(pack)
    return pack


def validate_content_pack(pack: ContentPack) -> None:
    """Fail loudly at load time rather than mysteriously at turn 40."""
    problems: list[str] = []

    location_keys = {loc.get("key") for loc in pack.locations}
    faction_keys = {f.get("key") for f in pack.factions}
    character_keys = {c.get("key") for c in pack.characters}
    item_keys = {i.get("key") for i in pack.items}
    skill_keys = {s.get("key") for s in pack.skills}
    fact_keys = {f.get("key") for f in pack.facts}
    thread_keys = {t.get("key") for t in pack.plot_threads}
    director_event_types = set(pack.rule("director.allowed_event_types", []) or [])

    if len(location_keys) != len(pack.locations):
        problems.append("duplicate location keys")
    if len(character_keys) != len(pack.characters):
        problems.append("duplicate character keys")

    for loc in pack.locations:
        parent = loc.get("parent")
        if parent is not None and parent not in location_keys:
            problems.append(f"location {loc.get('key')} has unknown parent {parent!r}")
        if loc.get("faction") and loc["faction"] not in faction_keys:
            problems.append(f"location {loc.get('key')} has unknown faction {loc['faction']!r}")
        for dest in (loc.get("travel") or {}):
            if dest not in location_keys:
                problems.append(f"location {loc.get('key')} travels to unknown {dest!r}")

    for ch in pack.characters:
        key = ch.get("key")
        home_key = ch.get("location")
        if home_key is not None and home_key not in location_keys:
            problems.append(f"character {key} is at unknown location {home_key!r}")
        if ch.get("faction") and ch["faction"] not in faction_keys:
            problems.append(f"character {key} belongs to unknown faction {ch['faction']!r}")
        realm = ch.get("realm", "mortal")
        if not pack.realms.has_realm(realm):
            problems.append(f"character {key} has unknown realm {realm!r}")
        else:
            stage = ch.get("realm_stage", pack.realms.first_stage(realm).key)
            try:
                pack.realms.stage(realm, stage)
            except ContentValidationError:
                problems.append(f"character {key} has unknown stage {stage!r} in realm {realm!r}")
        for skill_key in ch.get("skills", []) or []:
            if skill_key not in skill_keys:
                problems.append(f"character {key} knows unknown skill {skill_key!r}")
        for entry in ch.get("items", []) or []:
            if entry.get("key") not in item_keys:
                problems.append(f"character {key} owns unknown item {entry.get('key')!r}")

    for rel in pack.seed_relationships:
        for side in ("a", "b"):
            if rel.get(side) not in character_keys:
                problems.append(f"relationship references unknown character {rel.get(side)!r}")

    for f in pack.facts:
        for holder in (f.get("initial_knowledge") or {}):
            if holder not in character_keys:
                problems.append(f"fact {f.get('key')} grants knowledge to unknown {holder!r}")

    for thread in pack.plot_threads:
        for participant in thread.get("participants", []) or []:
            if participant not in character_keys:
                problems.append(
                    f"plot thread {thread.get('key')} names unknown participant {participant!r}"
                )
        for fact_key in thread.get("related_facts", []) or []:
            if fact_key not in fact_keys:
                problems.append(f"plot thread {thread.get('key')} cites unknown fact {fact_key!r}")
        for beat in thread.get("scheduled_beats", []) or []:
            offset = beat.get("at_minutes_from_start")
            if not isinstance(offset, int) or offset < 0:
                problems.append(
                    f"plot thread {thread.get('key')} has invalid scheduled beat time {offset!r}"
                )
            event_type = beat.get("event_type", "FORESHADOWING")
            if event_type not in director_event_types:
                problems.append(
                    f"plot thread {thread.get('key')} schedules disallowed event {event_type!r}"
                )
            for participant in beat.get("participants", []) or []:
                if participant not in character_keys:
                    problems.append(
                        f"plot thread {thread.get('key')} schedules unknown participant "
                        f"{participant!r}"
                    )

    for quest in pack.quests:
        giver = quest.get("giver")
        if giver and giver not in character_keys:
            problems.append(f"quest {quest.get('key')} has unknown giver {giver!r}")
        thread_key = quest.get("plot_thread")
        if thread_key and thread_key not in thread_keys:
            problems.append(f"quest {quest.get('key')} references unknown thread {thread_key!r}")

    start = pack.world_meta.get("start_location")
    if start and start not in location_keys:
        problems.append(f"world start_location {start!r} does not exist")

    if problems:
        raise ContentValidationError(
            f"content pack {pack.key!r} failed validation", problems=problems
        )

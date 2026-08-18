"""Deterministic v1 -> v2 projection used while bundled worlds migrate."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

from engine.contentpack.pack import ContentPack
from engine.contentpack.schema_v2 import ContentPackageV2


def trusted_plugin_tree_checksum(root: Path) -> str:
    """Hash every Python source file used by an installed trusted plugin."""
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.py"), key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def project_v1_as_v2(
    pack: ContentPack,
    *,
    slug: str | None = None,
    rating: str = "16+",
    tags: list[str] | None = None,
) -> ContentPackageV2:
    story = pack.story
    scenario_key = "main_story"
    manifest: dict[str, Any] = {
        "schema_version": "2.0",
        "key": pack.key,
        "slug": slug or pack.key.replace("_", "-"),
        "title": str(story.get("title") or pack.name),
        "summary": str(story.get("premise") or pack.world_meta.get("description", ""))[:1000],
        "version": str(pack.meta.get("version", "1.0.0")),
        "locale": str(pack.meta.get("language", "zh-CN")),
        "rating": rating,
        "tags": tags or [str(pack.meta.get("genre", "interactive-fiction"))],
        "engine": {
            "api_version": "2",
            "min_version": str(pack.meta.get("engine_min_version", "0.2.0")),
            "max_version": pack.meta.get("engine_max_version"),
        },
        "entry_scenario": scenario_key,
        "player_fields": pack.meta.get("player_fields") or [
            {"key": "name", "label": pack.vocabulary.get("player_name_label", "Name"), "type": "text", "required": True},
            {"key": "age", "label": pack.vocabulary.get("player_age_label", "Age"), "type": "integer", "required": True, "default": 18, "minimum": 18, "maximum": 80},
            {"key": "background", "label": pack.vocabulary.get("player_background_label", "Background"), "type": "text", "required": False},
        ],
        "capabilities": ["free_text", "relationships", "inventory", "quests", "saves"],
        "theme": pack.meta.get("theme", {}),
        "assets": pack.meta.get("assets", []),
        "trusted_rule_plugin": (
            str(pack.meta["rule_plugin"].get("path")) if pack.meta.get("rule_plugin") else None
        ),
    }
    world = deepcopy(pack.world_meta)
    plugin_declaration = deepcopy(pack.meta.get("rule_plugin"))
    if plugin_declaration:
        world["trusted_rule_plugin"] = plugin_declaration
        world["trusted_rule_plugin_sha256"] = trusted_plugin_tree_checksum(pack.root)

    resource_definitions = deepcopy(pack.meta.get("resource_definitions", []))
    if not resource_definitions:
        resource_definitions = [
            {"key": "health", "label": pack.vocabulary.get("resource_labels", {}).get("health", "Health"), "minimum": 0, "maximum": 100, "default": 100},
        ]
        if any(realm.max_spiritual_power > 0 for realm in pack.realms.realms):
            resource_definitions.append(
                {"key": "spiritual_power", "label": pack.vocabulary.get("profile_labels", {}).get("power", "Power"), "minimum": 0, "maximum": 100, "default": 0}
            )
    progression_definitions = deepcopy(pack.meta.get("progression_definitions", [])) or [
        {
            "key": str(pack.meta.get("primary_progression_key", "primary")),
            "label": pack.vocabulary.get("profile_labels", {}).get("realm", "Progression"),
            "tiers": [
                {"key": realm.key, "label": realm.name, "order": index}
                for index, realm in enumerate(pack.realms.realms)
            ],
        }
    ]

    content = {
        "world": world,
        "story": deepcopy(story),
        "endings": deepcopy(story.get("endings", []) or []),
        "scenarios": [
            {
                "key": scenario_key,
                "title": str(story.get("title") or pack.name),
                "premise": str(story.get("premise", "")),
                "start_location": str(
                    story.get("opening_location") or pack.world_meta.get("start_location")
                ),
                "player_template": story.get("player_template", {}),
                "initial_threads": [str(item.get("key")) for item in pack.plot_threads],
            }
        ],
        "locations": pack.locations,
        "organizations": pack.factions,
        "characters": pack.characters,
        "relationships": pack.seed_relationships,
        "facts": pack.facts,
        "items": pack.items,
        "abilities": pack.skills,
        "quests": pack.quests,
        "plot_threads": pack.plot_threads,
        "clocks": pack.clocks,
        "event_templates": pack.event_types,
        "offline_templates": pack.offline_templates,
        "npc_templates": pack.npc_templates,
        "engine_rules": pack.rules,
        "calendar": pack.calendar,
        "narrative": {"style": pack.narrative_style, "templates": pack.narrative_templates},
        "vocabulary": pack.vocabulary,
        "attributes": deepcopy(pack.meta.get("attribute_definitions", [])) or [
            {"key": key, "label": key, "type": "number"}
            for key in ("strength", "agility", "perception", "intelligence", "willpower", "charisma")
        ],
        "resources": resource_definitions,
        "progressions": progression_definitions,
        "rules": pack.declarative_rules,
    }
    author_tests = deepcopy(pack.meta.get("author_tests", [])) or [
        {
            "key": "official_opening_state",
            "name": "Official content opening state is playable",
            "scenario": scenario_key,
            "assertions": [
                {
                    "path": "player.location",
                    "op": "eq",
                    "expected": content["scenarios"][0]["start_location"],
                },
                {"path": "characters.player.alive", "op": "eq", "expected": True},
            ],
        }
    ]
    return ContentPackageV2.model_validate(
        {"manifest": manifest, "content": content, "author_tests": author_tests}
    )

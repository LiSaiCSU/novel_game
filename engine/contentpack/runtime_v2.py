"""Adapt a compiled Content Pack v2 artifact to the simulation runtime."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from engine.contentpack.pack import ContentPack, validate_content_pack
from engine.contentpack.realms import RealmLadder
from engine.contentpack.schema_v2 import ContentPackageV2

_BASE_EVENT_TYPES = [
    "MOVE",
    "CONVERSATION",
    "TRADE",
    "REST",
    "PROMISE",
    "SECRET_DISCLOSURE",
    "ITEM_ACQUIRED",
    "QUEST_ACCEPTED",
    "QUEST_COMPLETED",
    "QUEST_FAILED",
    "RELATIONSHIP_SHIFT",
    "REJECTED_ACTION",
    "OBSERVATION",
    "NPC_RETURN",
    "NPC_DEPARTURE",
    "NPC_APPROACH",
    "RUMOR_SPREAD",
    "FACTION_MOVE",
    "QUEST_OFFER",
    "DISCOVERY",
    "ENVIRONMENT_SHIFT",
    "CONFRONTATION",
    "RESOURCE_CHANGE",
    "FORESHADOWING",
    "OFFLINE_WORLD_EVENT",
    "SCHEDULE_MOVE",
]


def _generic_calendar() -> dict[str, Any]:
    return {
        "epoch_label": "Story",
        "epoch_year": 2026,
        "minutes_per_hour": 60,
        "hours_per_day": 24,
        "days_per_month": 30,
        "months_per_year": 12,
        "day_phases": [
            {"key": "night", "name": "Night", "start_hour": 0, "end_hour": 6},
            {"key": "morning", "name": "Morning", "start_hour": 6, "end_hour": 12},
            {"key": "afternoon", "name": "Afternoon", "start_hour": 12, "end_hour": 18},
            {"key": "evening", "name": "Evening", "start_hour": 18, "end_hour": 24},
        ],
        "shichen": [],
        "seasons": [],
        "month_names": [str(index) for index in range(1, 13)],
        "start_year": 2026,
        "start_month": 1,
        "start_day": 1,
        "start_hour": 9,
        "start_minute": 0,
        "format": "{year}-{month}-{day} {phase}",
    }


def _generic_rules(event_types: list[dict[str, Any]]) -> dict[str, Any]:
    allowed = [str(item["key"]) for item in event_types]
    return {
        "action_plan": {"max_total_minutes": 1440},
        "time_costs": {
            "TALK": {"min": 5, "max": 30},
            "ASK": {"min": 5, "max": 30},
            "CONVERSATION": {"min": 5, "max": 40},
            "OBSERVE": {"min": 5, "max": 20},
            "SEARCH": {"min": 10, "max": 90},
            "MOVE_LOCAL": {"min": 2, "max": 30},
            "MOVE_REGIONAL": {"min": 30, "max": 180},
            "REST": {"min": 30, "max": 480},
            "WAIT": {"min": 5, "max": 180},
            "CUSTOM": {"min": 5, "max": 60},
            "SECLUSION_MAX_MINUTES": 120960,
        },
        "relationship": {
            "ranges": {
                "affection": {"min": -100, "max": 100},
                "trust": {"min": -100, "max": 100},
                "respect": {"min": -100, "max": 100},
                "fear": {"min": 0, "max": 100},
                "hatred": {"min": 0, "max": 100},
                "suspicion": {"min": 0, "max": 100},
                "dependency": {"min": 0, "max": 100},
                "familiarity": {"min": 0, "max": 100},
                "boundaries": {"min": 0, "max": 100},
            },
            "max_delta_per_event": {"trivial": 2, "minor": 5, "major": 15, "life_changing": 35},
            "familiarity_gain_per_interaction": 1,
        },
        "inventory": {"max_slots": 40},
        "economy": {"currency_key": "currency", "buy_markup": 1.0, "sell_discount": 0.5},
        "information": {"confidence_decay_per_hop": 0.25, "spread_chance_per_day": {}},
        "memory": {"top_k": 8, "min_importance": 0.2, "recency_half_life_minutes": 20160},
        "narrative": {
            "tension_start": 20,
            "tension_decay_per_day": 2,
            "tension_gain_by_importance": 12,
            "high_threshold": 75,
            "max_consecutive_high_turns": 3,
        },
        "director": {
            "min_interval_turns": 3,
            "max_events_per_day": 2,
            "max_schedule_delay_minutes": 518400,
            "allowed_event_types": allowed,
        },
        "simulation": {
            "tick_minutes": {"lod1": 240, "lod2": 1440, "lod3": 10080},
            "max_materialized_events_per_jump": 48,
            "npc_goal_action_interval_minutes": 720,
        },
        "auto_advance": {
            "max_steps": 4,
            "max_minutes": 240,
            "npc_llm_per_step": 1,
            "engaging_actions": ["TALK", "ASK", "SEARCH", "OBSERVE"],
            "hostile_actions": [],
            "offer_events": ["QUEST_OFFER", "CONFRONTATION"],
        },
        "consistency": {
            "strict": True,
            "checks": ["alive", "location", "inventory", "knowledge", "time"],
        },
        "reputation": {
            "ranges": {"global": {"min": -100, "max": 100}, "faction": {"min": -100, "max": 100}}
        },
        "combat": {
            "health_regen_per_hour": 0.03,
            "spiritual_power_regen_per_hour": 0,
            "hit_chance": {"base": 0.5, "min": 0.05, "max": 0.95},
        },
    }


def _generic_ladder(package: ContentPackageV2) -> RealmLadder:
    progression = package.content.progressions[0] if package.content.progressions else None
    tiers: list[Any] = list(progression.tiers) if progression else []
    raw_tiers = [{"key": tier.key, "name": tier.label, "order": tier.order} for tier in tiers] or [
        {"key": "standard", "name": "Standard", "order": 0}
    ]
    return RealmLadder(
        {
            "progression_name": progression.key if progression else "primary",
            "realms": [
                {
                    **tier,
                    "stages": [{"key": "active", "name": "", "order": 0}],
                    "max_health": 100,
                    "max_spiritual_power": 0,
                    "playable_in_v1": True,
                }
                for tier in raw_tiers
            ],
        }
    )


def content_pack_from_v2(
    package: ContentPackageV2,
    *,
    content_dir: Path | str,
    scenario_key: str | None = None,
) -> ContentPack:
    """Create a safe runtime pack without executable code or another work's defaults."""
    del content_dir  # Kept in the public adapter signature for compatibility.
    document = package.content
    selected_scenario = scenario_key or package.manifest.entry_scenario
    scenario = next(item for item in document.scenarios if item.key == selected_scenario)
    ladder = _generic_ladder(package)
    default_realm = ladder.realms[0].key

    locations: list[dict[str, Any]] = []
    for source in document.locations:
        item = deepcopy(source)
        item.setdefault("type", "scene")
        item.setdefault("danger", 0)
        item.setdefault("description", "")
        item.setdefault("travel", {})
        locations.append(item)

    characters: list[dict[str, Any]] = []
    for source in document.characters:
        item = deepcopy(source)
        item.setdefault("type", "NPC")
        item.setdefault("age", 18)
        item.setdefault("gender", "unspecified")
        if not ladder.has_realm(str(item.get("realm", ""))):
            item["realm"] = default_realm
        item["realm_stage"] = "active"
        item.setdefault("stats", item.get("attributes", {}))
        item.setdefault("personality", {})
        item.setdefault("emotion", {})
        item.setdefault("items", [])
        item.setdefault("skills", [])
        item.setdefault("schedule", {})
        characters.append(item)

    abilities: list[dict[str, Any]] = []
    for source in document.abilities:
        item = deepcopy(source)
        required_realm = str(item.get("required_realm", default_realm))
        if not ladder.has_realm(required_realm):
            required_realm = default_realm
        item["required_realm"] = required_realm
        item["required_stage"] = ladder.first_stage(required_realm).key
        abilities.append(item)

    event_types = deepcopy(document.event_templates) or [
        {"key": key, "importance": 0.1, "visibility": "LOCAL"} for key in _BASE_EVENT_TYPES
    ]
    item_type_keys = sorted({str(item.get("type", "item")) for item in document.items}) or ["item"]
    rarity_keys = sorted({str(item.get("rarity", "common")) for item in document.items}) or [
        "common"
    ]
    primary_progression = document.progressions[0].key if document.progressions else "primary"
    meta = {
        "key": package.manifest.key,
        "name": package.manifest.title,
        "version": package.manifest.version,
        "language": package.manifest.locale,
        "player_fields": [item.model_dump(mode="json") for item in package.manifest.player_fields],
        "primary_progression_key": primary_progression,
        "resource_definitions": [item.model_dump(mode="json") for item in document.resources],
        "progression_definitions": [item.model_dump(mode="json") for item in document.progressions],
        "player_template": deepcopy(scenario.player_template),
        "world": {**deepcopy(document.world), "start_location": scenario.start_location},
        "story": {
            **deepcopy(document.story),
            **(
                {"endings": [item.model_dump(mode="json") for item in document.endings]}
                if document.endings
                else {}
            ),
            "title": scenario.title,
            "premise": scenario.premise,
            "opening_location": scenario.start_location,
            "starter_items": scenario.player_template.get("items", []),
            "relationship_boundaries": str(
                document.story.get(
                    "relationship_boundaries", document.world.get("relationship_boundaries", "")
                )
            ),
        },
        "narrative_style": deepcopy(document.narrative.get("style", document.narrative)),
        "vocabulary": deepcopy(document.vocabulary),
        "theme": package.manifest.theme.model_dump(),
    }
    location_types = sorted({str(item["type"]) for item in locations})
    pack = ContentPack(
        key=package.manifest.key,
        root=Path("<compiled-content-pack-v2>"),
        meta=meta,
        calendar=deepcopy(document.calendar) or _generic_calendar(),
        realms=ladder,
        rules=deepcopy(document.engine_rules) or _generic_rules(event_types),
        locations=locations,
        location_types=[{"key": key, "name": key} for key in location_types],
        factions=deepcopy(document.organizations),
        characters=characters,
        seed_relationships=deepcopy(document.relationships),
        npc_templates=deepcopy(document.npc_templates),
        items=deepcopy(document.items),
        item_types=[{"key": key, "name": key} for key in item_type_keys],
        rarities=[{"key": key, "name": key, "value_multiplier": 1} for key in rarity_keys],
        skills=abilities,
        facts=deepcopy(document.facts),
        plot_threads=deepcopy(document.plot_threads),
        clocks=deepcopy(document.clocks),
        quests=deepcopy(document.quests),
        event_types=event_types,
        offline_templates=deepcopy(document.offline_templates),
        narrative_templates=deepcopy(document.narrative.get("templates", {})),
        declarative_rules=[item.model_dump(mode="json") for item in document.rules],
        rule_plugin=None,
    )
    validate_content_pack(pack)
    return pack

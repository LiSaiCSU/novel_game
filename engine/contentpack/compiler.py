"""Content Pack v2 validation and immutable release compilation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from packaging.version import InvalidVersion, Version

from engine.contentpack.declarative import DeclarativeRule
from engine.contentpack.schema_v2 import (
    ENGINE_API_VERSION,
    ENGINE_VERSION,
    CompiledRelease,
    ContentPackageV2,
)
from engine.core.errors import ContentValidationError


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compile_package(package: ContentPackageV2 | dict[str, Any]) -> CompiledRelease:
    raw = package.model_dump(mode="python") if isinstance(package, ContentPackageV2) else package
    parsed = ContentPackageV2.model_validate(raw)
    problems = validate_package_graph(parsed)
    if problems:
        raise ContentValidationError(
            f"content package {parsed.manifest.key!r} failed v2 validation", problems=problems
        )
    payload = parsed.model_dump(mode="json")
    checksum = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return CompiledRelease(
        manifest=parsed.manifest,
        content=parsed.content,
        author_tests=parsed.author_tests,
        checksum=checksum,
        compiled_at=datetime.now(UTC).isoformat(),
    )


def load_author_package(path: Path | str) -> ContentPackageV2:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        raw = json.load(handle) if source.suffix.lower() == ".json" else yaml.safe_load(handle)
    return ContentPackageV2.model_validate(raw)


def write_compiled_release(release: CompiledRelease, path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(release.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def validate_package_graph(package: ContentPackageV2) -> list[str]:
    content = package.content
    problems: list[str] = []
    location_keys = _keys(content.locations, "location", problems)
    organization_keys = _keys(content.organizations, "organization", problems)
    character_keys = _keys(content.characters, "character", problems)
    fact_keys = _keys(content.facts, "fact", problems)
    item_keys = _keys(content.items, "item", problems)
    ability_keys = _keys(content.abilities, "ability", problems)
    quest_keys = _keys(content.quests, "quest", problems)
    thread_keys = _keys(content.plot_threads, "plot thread", problems)
    resource_keys = {item.key for item in content.resources}
    progression_keys = {item.key for item in content.progressions}
    attribute_keys = _keys(content.attributes, "attribute", problems)
    scenario_keys = [scenario.key for scenario in content.scenarios]
    author_test_keys = [test.key for test in package.author_tests]

    if package.manifest.engine.api_version != ENGINE_API_VERSION:
        problems.append(
            f"engine API {package.manifest.engine.api_version!r} is incompatible with {ENGINE_API_VERSION!r}"
        )
    try:
        current_version = Version(ENGINE_VERSION)
        minimum_version = Version(package.manifest.engine.min_version)
        maximum_version = (
            Version(package.manifest.engine.max_version)
            if package.manifest.engine.max_version
            else None
        )
        if current_version < minimum_version or (
            maximum_version is not None and current_version > maximum_version
        ):
            problems.append(
                f"engine version {ENGINE_VERSION!r} is outside supported range "
                f"{package.manifest.engine.min_version!r}.."
                f"{package.manifest.engine.max_version or '*'}"
            )
    except InvalidVersion:
        problems.append("engine min_version/max_version must use valid version syntax")
    if len(scenario_keys) != len(set(scenario_keys)):
        problems.append("duplicate scenario keys")
    if len(author_test_keys) != len(set(author_test_keys)):
        problems.append("duplicate author test keys")
    if len(package.manifest.assets) != len({asset.key for asset in package.manifest.assets}):
        problems.append("duplicate asset keys")
    if len(content.resources) != len({item.key for item in content.resources}):
        problems.append("duplicate resource keys")
    if len(content.progressions) != len({item.key for item in content.progressions}):
        problems.append("duplicate progression keys")
    ending_rows = [item.model_dump(mode="python") for item in content.endings]
    ending_keys = _keys(ending_rows, "ending", problems)
    if len(ending_keys) != len(content.endings):
        problems.append("duplicate or missing ending keys")
    for ending in content.endings:
        lead = ending.lead
        if lead and lead not in character_keys:
            problems.append(f"ending {ending.key!r} references unknown lead {lead!r}")

    if package.manifest.entry_scenario not in set(scenario_keys):
        problems.append("manifest entry_scenario does not exist")
    for scenario in content.scenarios:
        if scenario.start_location not in location_keys:
            problems.append(
                f"scenario {scenario.key!r} references unknown location {scenario.start_location!r}"
            )
        for initial_thread in scenario.initial_threads:
            if initial_thread not in thread_keys:
                problems.append(
                    f"scenario {scenario.key!r} references unknown thread {initial_thread!r}"
                )
    for test in package.author_tests:
        scenario_key = test.scenario or package.manifest.entry_scenario
        if scenario_key not in set(scenario_keys):
            problems.append(
                f"author test {test.key!r} references unknown scenario {scenario_key!r}"
            )
        for lead_key in test.fixtures.relationships:
            if lead_key not in character_keys:
                problems.append(
                    f"author test {test.key!r} references unknown relationship lead {lead_key!r}"
                )
        for actor_key, facts in test.fixtures.knowledge.items():
            if actor_key not in character_keys | {"player"}:
                problems.append(
                    f"author test {test.key!r} references unknown knowledge actor {actor_key!r}"
                )
            for test_fact_key in facts:
                if test_fact_key not in fact_keys:
                    problems.append(
                        f"author test {test.key!r} references unknown fact {test_fact_key!r}"
                    )
        for test_quest_key in test.fixtures.quests:
            if test_quest_key not in quest_keys:
                problems.append(
                    f"author test {test.key!r} references unknown quest {test_quest_key!r}"
                )
        for thread_key in test.fixtures.plot_threads:
            if thread_key not in thread_keys:
                problems.append(
                    f"author test {test.key!r} references unknown plot thread {thread_key!r}"
                )
        assertion_roots = {
            "world",
            "player",
            "characters",
            "relationships",
            "knowledge",
            "quests",
            "plot_threads",
            "endings",
            "events",
            "last_turn",
        }
        for assertion in test.assertions:
            segments = assertion.path.split(".")
            root = segments[0]
            if root not in assertion_roots:
                problems.append(
                    f"author test {test.key!r} assertion uses unknown root {root!r}"
                )
                continue
            reference = segments[1] if len(segments) > 1 else None
            if root == "characters" and reference not in character_keys | {"player"}:
                problems.append(
                    f"author test {test.key!r} assertion references unknown character {reference!r}"
                )
            elif root == "relationships" and reference not in character_keys:
                problems.append(
                    f"author test {test.key!r} assertion references unknown relationship {reference!r}"
                )
            elif root == "knowledge" and reference not in character_keys | {"player"}:
                problems.append(
                    f"author test {test.key!r} assertion references unknown knowledge actor {reference!r}"
                )
            elif root == "knowledge" and len(segments) > 2 and segments[2] not in fact_keys:
                problems.append(
                    f"author test {test.key!r} assertion references unknown fact {segments[2]!r}"
                )
            elif root == "quests" and reference not in quest_keys:
                problems.append(
                    f"author test {test.key!r} assertion references unknown quest {reference!r}"
                )
            elif root == "plot_threads" and reference not in thread_keys:
                problems.append(
                    f"author test {test.key!r} assertion references unknown plot thread {reference!r}"
                )
            elif root == "endings" and reference not in ending_keys:
                problems.append(
                    f"author test {test.key!r} assertion references unknown ending {reference!r}"
                )
    for location in content.locations:
        parent = location.get("parent")
        if parent and parent not in location_keys:
            problems.append(f"location {location.get('key')!r} has unknown parent {parent!r}")
        for destination in location.get("travel") or {}:
            if destination not in location_keys:
                problems.append(
                    f"location {location.get('key')!r} travels to unknown {destination!r}"
                )
    for relationship in content.relationships:
        for side in ("a", "b"):
            relationship_key = relationship.get(side)
            if relationship_key not in character_keys | {"player"}:
                problems.append(f"relationship references unknown character {relationship_key!r}")
    for organization in content.organizations:
        organization_key = organization.get("key")
        for field in ("headquarters",):
            reference = organization.get(field)
            if reference and reference not in location_keys:
                problems.append(
                    f"organization {organization_key!r} references unknown location {reference!r}"
                )
        for reference in organization.get("territory", []) or []:
            if reference not in location_keys:
                problems.append(
                    f"organization {organization_key!r} references unknown location {reference!r}"
                )
        leader = organization.get("leader")
        if leader and leader not in character_keys:
            problems.append(
                f"organization {organization_key!r} references unknown leader {leader!r}"
            )
        for reference in (organization.get("alliances", []) or []) + (
            organization.get("enemies", []) or []
        ):
            if reference not in organization_keys:
                problems.append(
                    f"organization {organization_key!r} references unknown organization {reference!r}"
                )
    for character in content.characters:
        character_key = character.get("key")
        character_location = character.get("location")
        if character_location and character_location not in location_keys:
            problems.append(
                f"character {character_key!r} references unknown location {character_location!r}"
            )
        character_organization = character.get("faction") or character.get("organization")
        if character_organization and character_organization not in organization_keys:
            problems.append(
                f"character {character_key!r} references unknown organization {character_organization!r}"
            )
        for entry in character.get("items", []) or []:
            reference = entry.get("key") if isinstance(entry, dict) else entry
            if reference not in item_keys:
                problems.append(
                    f"character {character_key!r} references unknown item {reference!r}"
                )
        for reference in character.get("skills", []) or []:
            if reference not in ability_keys:
                problems.append(
                    f"character {character_key!r} references unknown ability {reference!r}"
                )
        for slot in (character.get("schedule", {}) or {}).get("slots", []) or []:
            reference = slot.get("location")
            if reference and reference not in location_keys:
                problems.append(
                    f"character {character_key!r} schedule references unknown location {reference!r}"
                )
    for fact in content.facts:
        fact_key = fact.get("key")
        for holder in fact.get("initial_knowledge", {}) or {}:
            if holder not in character_keys | {"player"}:
                problems.append(
                    f"fact {fact_key!r} grants knowledge to unknown character {holder!r}"
                )
    for thread in content.plot_threads:
        plot_thread_key = thread.get("key")
        for participant in thread.get("participants", []) or []:
            if participant not in character_keys | {"player"}:
                problems.append(
                    f"plot thread {plot_thread_key!r} references unknown participant {participant!r}"
                )
        for reference in thread.get("related_facts", []) or []:
            if reference not in fact_keys:
                problems.append(
                    f"plot thread {plot_thread_key!r} references unknown fact {reference!r}"
                )
    for quest in content.quests:
        quest_key = quest.get("key")
        giver = quest.get("giver")
        if giver and giver not in character_keys | {"player"}:
            problems.append(f"quest {quest_key!r} references unknown giver {giver!r}")
        quest_thread = quest.get("plot_thread")
        if quest_thread and quest_thread not in thread_keys:
            problems.append(f"quest {quest_key!r} references unknown plot thread {quest_thread!r}")
        goal_location = (quest.get("goal") or {}).get("location")
        if goal_location and goal_location not in location_keys:
            problems.append(f"quest {quest_key!r} references unknown location {goal_location!r}")
    for raw_rule in content.rules:
        try:
            rule = (
                raw_rule
                if isinstance(raw_rule, DeclarativeRule)
                else DeclarativeRule.model_validate(raw_rule)
            )
        except ValueError as exc:
            invalid_rule_key = raw_rule.get("key") if isinstance(raw_rule, dict) else ""
            problems.append(f"rule {invalid_rule_key!r} is invalid: {exc}")
            continue
        for effect in rule.effects:
            if effect.op == "adjust_player_resource" and effect.field not in resource_keys:
                problems.append(f"rule {rule.key!r} targets unknown resource {effect.field!r}")
            elif effect.op == "set_player_data":
                namespace, key = effect.field.split(".", 1)
                declared = {
                    "attributes": attribute_keys,
                    "resources": resource_keys,
                    "progressions": progression_keys,
                }.get(namespace)
                if declared is not None and key not in declared:
                    problems.append(f"rule {rule.key!r} targets unknown {namespace[:-1]} {key!r}")
            elif effect.op == "relationship_delta" and effect.target not in character_keys:
                problems.append(f"rule {rule.key!r} targets unknown character {effect.target!r}")
            elif (
                effect.op in {"inventory_add", "inventory_remove"}
                and effect.target not in item_keys
            ):
                problems.append(f"rule {rule.key!r} targets unknown item {effect.target!r}")
            elif effect.op == "quest_status" and effect.target not in quest_keys:
                problems.append(f"rule {rule.key!r} targets unknown quest {effect.target!r}")
            elif effect.op == "plot_thread_update" and effect.target not in thread_keys:
                problems.append(f"rule {rule.key!r} targets unknown plot thread {effect.target!r}")
            elif effect.op == "location_flag" and effect.target not in location_keys:
                problems.append(f"rule {rule.key!r} targets unknown location {effect.target!r}")

    if content.locations and not _entry_reaches_all(content, package.manifest.entry_scenario):
        problems.append("location graph contains nodes unreachable from the entry scenario")
    return problems


def _keys(rows: list[dict[str, Any]], label: str, problems: list[str]) -> set[str]:
    keys = [str(row.get("key", "")) for row in rows]
    if "" in keys:
        problems.append(f"{label} is missing a key")
    if len(keys) != len(set(keys)):
        problems.append(f"duplicate {label} keys")
    for key in keys:
        if key and not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", key):
            problems.append(f"{label} key {key!r} is not stable snake_case")
    return set(keys)


def _entry_reaches_all(content: Any, entry_scenario: str) -> bool:
    scenario = next((item for item in content.scenarios if item.key == entry_scenario), None)
    if scenario is None:
        return False
    graph = {
        str(row.get("key")): set((row.get("travel") or {}).keys()) for row in content.locations
    }
    # Parent/child containment is navigable even when an author omits duplicate
    # travel edges for every room in a compound location.
    for row in content.locations:
        key = str(row.get("key"))
        parent = row.get("parent")
        if parent and str(parent) in graph:
            graph[key].add(str(parent))
            graph[str(parent)].add(key)
    visited: set[str] = set()
    pending = [scenario.start_location]
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        pending.extend(graph.get(key, set()) - visited)
    return visited == set(graph)

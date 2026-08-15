from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from apps.authoring.testing import run_author_tests
from database.memory_uow import MemoryStore, MemoryUnitOfWork
from engine.actions.schema import Action, ActionOutcome
from engine.contentpack.compiler import compile_package, validate_package_graph
from engine.contentpack.declarative import DeclarativeRule, RuleLanguageError, evaluate
from engine.contentpack.declarative_runtime import apply_declarative_rules
from engine.contentpack.legacy_v2 import project_v1_as_v2
from engine.contentpack.pack import load_content_pack
from engine.contentpack.runtime_v2 import content_pack_from_v2
from engine.contentpack.schema_v2 import AuthorTestCase, ResourceDefinition
from engine.core.config import Settings
from engine.core.errors import ContentValidationError
from engine.core.ids import PLAYER_KEY
from engine.core.mutations import ChangeSet
from engine.core.types import ActionType, QuestStatus
from engine.endings import build_ending_context, evaluate_endings
from engine.world.seeder import PlayerSpec, build_world
from engine.world.state_view import build_world_state

CONTENT = Path(__file__).resolve().parents[2] / "content"


@pytest.mark.parametrize(
    "key",
    ("tomb_lantern_v1", "fog_harbor_v1", "spirit_pact_v1"),
)
def test_new_official_content_has_a_valid_landscape_cover(key: str) -> None:
    pack = load_content_pack(CONTENT, key)
    package = project_v1_as_v2(pack)
    covers = [asset for asset in package.manifest.assets if asset.kind == "cover"]

    assert len(covers) == 1
    source = pack.root / "assets" / Path(covers[0].path).name
    assert source.is_file()
    with Image.open(source) as image:
        assert image.format == "PNG"
        assert image.width >= 1200
        assert image.width * 2 == image.height * 3


@pytest.mark.parametrize(
    "key",
    (
        "cultivation_v1",
        "campus_romance_v1",
        "tomb_lantern_v1",
        "fog_harbor_v1",
        "spirit_pact_v1",
    ),
)
def test_official_content_has_a_three_act_player_first_opening(key: str) -> None:
    source = load_content_pack(CONTENT, key)
    blueprint = source.story.get("opening_blueprint", {})

    assert blueprint.get("player_context")
    assert blueprint.get("choice_gate")
    assert blueprint.get("humor_rule")
    assert len(blueprint.get("acts", [])) == 3
    assert all(act.get("purpose") and act.get("must_show") for act in blueprint["acts"])
    assert "templates" not in source.narrative_templates
    assert {"action", "query", "knowledge_hedges", "npc_goal_action"} <= set(
        source.narrative_templates
    )

    package = project_v1_as_v2(source)
    runtime = content_pack_from_v2(package, content_dir=CONTENT)
    assert runtime.story["opening_blueprint"] == blueprint
    assert runtime.meta["player_fields"] == [
        field.model_dump(mode="json") for field in package.manifest.player_fields
    ]


def test_campus_pack_is_full_v2_reference_work() -> None:
    pack = load_content_pack(CONTENT, "campus_romance_v1")
    package = project_v1_as_v2(pack, slug="spring-messages", tags=["校园", "女性向"])
    release = compile_package(package)

    assert len(pack.locations) == 14
    assert len(pack.characters) == 12
    assert len(pack.plot_threads) == 6
    assert sum(len(row.get("scheduled_beats", [])) for row in pack.plot_threads) == 24
    assert len(pack.quests) == 12
    assert len(pack.story["endings"]) == 9
    assert pack.rule_plugin is None
    assert len(package.content.story["endings"]) == 9
    assert {item.key for item in package.content.resources} == {"health", "energy"}
    assert {item.key for item in package.content.progressions} == {
        "education", "festival_reputation"
    }
    assert "spiritual_power" not in package.model_dump_json()
    assert "cultivation" not in package.model_dump_json()
    assert {rule.key for rule in package.content.rules} == {
        "focused_action_costs_energy", "rest_restores_energy"
    }
    assert len(release.checksum) == 64


@pytest.mark.asyncio
async def test_all_official_content_declares_and_passes_author_tests() -> None:
    for key in (
        "cultivation_v1", "campus_romance_v1", "tomb_lantern_v1",
        "fog_harbor_v1", "spirit_pact_v1",
    ):
        package = project_v1_as_v2(load_content_pack(CONTENT, key))
        suite = await run_author_tests(package, content_dir=str(CONTENT / key))

        assert suite.declared_tests > 0
        assert suite.passed, suite.model_dump(mode="json")


def test_release_checksum_uses_stable_capability_order() -> None:
    pack = load_content_pack(CONTENT, "campus_romance_v1")
    package = project_v1_as_v2(pack)
    package.manifest.capabilities = ["saves", "free_text", "saves", "inventory"]

    first = compile_package(package)
    second = compile_package(package.model_dump(mode="json"))

    assert first.manifest.capabilities == ["free_text", "inventory", "saves"]
    assert first.checksum == second.checksum


def test_compiler_enforces_engine_version_range() -> None:
    pack = load_content_pack(CONTENT, "campus_romance_v1")
    package = project_v1_as_v2(pack)
    assert package.manifest.engine.min_version == "0.2.0"

    package.manifest.engine.min_version = "99.0.0"
    with pytest.raises(ContentValidationError, match="failed v2 validation") as exc_info:
        compile_package(package)
    assert "outside supported range" in str(exc_info.value.context["problems"])


def test_official_release_uses_compiled_content_and_verified_plugin() -> None:
    from apps.api.runtime import ReleaseContentCache, RuntimeConfigurationError
    from database.bootstrap import SYSTEM_USER_ID
    from database.models.platform import ContentReleaseORM

    source = load_content_pack(CONTENT, "cultivation_v1")
    package = project_v1_as_v2(source)
    compiled = compile_package(package)
    release = ContentReleaseORM(
        id="release", project_id="project", revision_id="revision",
        owner_id=SYSTEM_USER_ID, version=package.manifest.version,
        checksum=compiled.checksum, title=package.manifest.title,
        summary="", locale="zh-CN", rating="16+", tags=[],
        artifact=compiled.model_dump(mode="json"), visibility="public",
        moderation_status="approved",
    )

    runtime = ReleaseContentCache().resolve(
        release, Settings(content_dir=str(CONTENT))
    )

    assert "runtime_pack_key" not in package.content.world
    assert runtime.rule_plugin is not None
    assert runtime.rule("time_costs.CULTIVATE.default") == source.rule(
        "time_costs.CULTIVATE.default"
    )

    release.owner_id = "not-the-system-owner"
    with pytest.raises(RuntimeConfigurationError, match="untrusted"):
        ReleaseContentCache().resolve(release, Settings(content_dir=str(CONTENT)))


def test_compiler_rejects_unreachable_locations_and_unsafe_rule() -> None:
    pack = load_content_pack(CONTENT, "campus_romance_v1")
    package = project_v1_as_v2(pack)
    package.content.locations.append({"key": "orphan", "name": "orphan"})
    package.content.rules.append(
        {"key": "bad", "condition": {"op": "not", "args": [{"op": "eval", "args": []}]}}
    )

    problems = validate_package_graph(package)
    assert any("unreachable" in item for item in problems)
    assert any("unsupported declarative operation" in item for item in problems)


def test_compiler_rejects_dangling_author_test_references() -> None:
    pack = load_content_pack(CONTENT, "campus_romance_v1")
    package = project_v1_as_v2(pack)
    package.author_tests = [
        AuthorTestCase.model_validate(
            {
                "key": "dangling",
                "name": "Dangling references are diagnosed before execution",
                "fixtures": {"quests": {"missing_quest": "completed"}},
                "assertions": [
                    {"path": "knowledge.player.missing_fact", "op": "eq", "expected": "KNOWN"}
                ],
            }
        )
    ]

    problems = validate_package_graph(package)

    assert any("unknown quest 'missing_quest'" in item for item in problems)
    assert any("unknown fact 'missing_fact'" in item for item in problems)


def test_declarative_language_is_typed_and_bounded() -> None:
    expression = {
        "op": "and",
        "args": [
            {"op": "gte", "args": [{"op": "get", "args": ["player.trust"]}, 50]},
            {"op": "eq", "args": [{"op": "get", "args": ["consent"]}, True]},
        ],
    }
    assert evaluate(expression, {"player": {"trust": 60}, "consent": True}) is True
    with pytest.raises(ValueError, match="unsupported"):
        evaluate({"op": "open_file", "args": ["secret"]}, {})
    with pytest.raises(RuleLanguageError, match="unsafe"):
        evaluate({"op": "get", "args": ["__class__"]}, {})


def test_creator_package_can_be_loaded_by_generic_runtime() -> None:
    source = load_content_pack(CONTENT, "campus_romance_v1")
    package = project_v1_as_v2(source)
    package.content.world.pop("runtime_pack_key", None)
    runtime = content_pack_from_v2(package, content_dir=CONTENT)

    assert runtime.key == package.manifest.key
    assert runtime.rule_plugin is None
    assert runtime.location(package.content.scenarios[0].start_location) is not None
    assert runtime.story["endings"] == [
        ending.model_dump(mode="json") for ending in package.content.endings
    ]
    assert runtime.rule("director.min_interval_turns") == source.rule(
        "director.min_interval_turns"
    )
    assert len(runtime.declarative_rules) == 2


@pytest.mark.asyncio
async def test_declarative_rule_changes_resources_and_audits_relationships() -> None:
    source = load_content_pack(CONTENT, "campus_romance_v1")
    package = project_v1_as_v2(source)
    package.content.world.pop("runtime_pack_key", None)
    package.content.resources.append(
        ResourceDefinition(key="energy", label="Energy", minimum=0, maximum=100, default=100)
    )
    package.content.rules = [
        DeclarativeRule.model_validate(
            {
                "key": "observe_costs_energy",
                "condition": {
                    "op": "eq",
                    "args": [{"op": "get", "args": ["action.action_type"]}, "OBSERVE"],
                },
                "effects": [
                    {"op": "adjust_player_resource", "field": "energy", "value": -10},
                    {
                        "op": "relationship_delta",
                        "target": "haruto",
                        "values": {"trust": 3, "boundaries": 2},
                    },
                ],
            }
        )
    ]
    runtime = content_pack_from_v2(package, content_dir=CONTENT)
    bundle = build_world(runtime, player=PlayerSpec(name="Tester", gender="female", age=20))
    store = MemoryStore()
    store.load(bundle)
    uow = MemoryUnitOfWork(store)
    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    state = await build_world_state(uow, runtime, bundle.world.id, player.id)
    changes = ChangeSet()

    applied = apply_declarative_rules(
        runtime,
        state,
        Action(action_type=ActionType.OBSERVE, actor_id=player.id),
        ActionOutcome(action_type=ActionType.OBSERVE, importance=0.4),
        changes,
    )
    await uow.apply(changes)

    assert applied == ["observe_costs_energy"]
    assert store.characters[player.id].resources["energy"]["current"] == 90
    assert {item.dimension for item in store.relationship_changes} == {"trust", "boundaries"}


@pytest.mark.asyncio
async def test_campus_pack_executes_its_own_energy_rule() -> None:
    source = load_content_pack(CONTENT, "campus_romance_v1")
    package = project_v1_as_v2(source)
    runtime = content_pack_from_v2(package, content_dir=CONTENT)
    bundle = build_world(runtime, player=PlayerSpec(name="Tester", gender="female", age=20))
    store = MemoryStore()
    store.load(bundle)
    uow = MemoryUnitOfWork(store)
    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    state = await build_world_state(uow, runtime, bundle.world.id, player.id)
    changes = ChangeSet()

    applied = apply_declarative_rules(
        runtime,
        state,
        Action(action_type=ActionType.OBSERVE, actor_id=player.id),
        ActionOutcome(action_type=ActionType.OBSERVE, importance=0.2),
        changes,
    )
    await uow.apply(changes)

    assert applied == ["focused_action_costs_energy"]
    assert store.characters[player.id].resources["energy"]["current"] == 76


@pytest.mark.asyncio
async def test_campus_all_nine_endings_and_romance_rejection_are_deterministic() -> None:
    source = load_content_pack(CONTENT, "campus_romance_v1")
    package = project_v1_as_v2(source)
    runtime = content_pack_from_v2(package, content_dir=CONTENT)
    bundle = build_world(runtime, player=PlayerSpec(name="Tester", gender="female", age=20))
    store = MemoryStore()
    store.load(bundle)
    uow = MemoryUnitOfWork(store)
    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    final_quest = next(quest for quest in store.quests.values() if quest.key == "quest_final_performance")
    final_quest.status = QuestStatus.COMPLETED
    lead_keys = ("haruto", "ren", "sora", "akira")
    for lead_key in lead_keys:
        lead = bundle.character_by_key(lead_key)
        assert lead is not None
        relationship = store.relationships[(lead.id, player.id)]
        relationship.affection = 55
        relationship.trust = 60
        relationship.respect = 50
        relationship.familiarity = 60
        relationship.boundaries = 70

    store.characters[player.id].properties["romance_consent"] = {
        key: "accepted" for key in lead_keys
    }
    state = await build_world_state(uow, runtime, bundle.world.id, player.id)
    context = await build_ending_context(uow, state, package.content.endings)
    romance = {
        ending.key
        for ending in evaluate_endings(package.content.endings, context)
        if ending.available and ending.type == "romance"
    }
    assert romance == {f"romance_{key}" for key in lead_keys}

    store.characters[player.id].properties["romance_consent"] = {
        key: "rejected" for key in lead_keys
    }
    state = await build_world_state(uow, runtime, bundle.world.id, player.id)
    context = await build_ending_context(uow, state, package.content.endings)
    available = {
        ending.key
        for ending in evaluate_endings(package.content.endings, context)
        if ending.available
    }
    assert not available.intersection({f"romance_{key}" for key in lead_keys})
    assert {f"bond_{key}" for key in lead_keys} <= available
    assert "independent_growth" in available

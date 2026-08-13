"""Deterministic Content Pack author-test runner shared by CLI and Studio."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import prompts
from database.memory_uow import MemoryStore, MemoryUnitOfWork
from engine.contentpack.pack import ContentPack
from engine.contentpack.runtime_v2 import content_pack_from_v2
from engine.contentpack.schema_v2 import AuthorAssertion, AuthorTestCase, ContentPackageV2
from engine.core.config import Settings
from engine.core.models import CharacterKnowledge, Relationship
from engine.core.types import KnowledgeSource, KnowledgeState, QuestStatus, ThreadStatus
from engine.endings import build_ending_context, evaluate_endings
from engine.orchestrator.factory import build_orchestrator
from engine.orchestrator.turn import TurnRequest, TurnResult
from engine.world.seeder import PlayerSpec, SeedBundle, build_world
from engine.world.state_view import build_world_state

_MISSING = object()
MAX_SUITE_ACTIONS = 80


class AssertionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    op: str
    passed: bool
    expected: Any = None
    actual: Any = None
    message: str = ""


class AuthorTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    passed: bool
    duration_ms: int = Field(ge=0)
    actions_run: int = Field(ge=0)
    assertions: list[AssertionResult] = Field(default_factory=list)
    error: str = ""


class AuthorTestSuiteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    declared_tests: int = Field(ge=0)
    total: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    results: list[AuthorTestResult] = Field(default_factory=list)


def _built_in_smoke(package: ContentPackageV2) -> AuthorTestCase:
    scenario = next(
        row for row in package.content.scenarios if row.key == package.manifest.entry_scenario
    )
    return AuthorTestCase(
        key="engine_seed_smoke",
        name="Engine seed smoke",
        scenario=scenario.key,
        assertions=[
            AuthorAssertion(path="player.name", op="exists"),
            AuthorAssertion(path="player.location", op="eq", expected=scenario.start_location),
            AuthorAssertion(path="world.current_minute", op="gte", expected=0),
        ],
    )


def _apply_fixtures(bundle: SeedBundle, test: AuthorTestCase) -> None:
    characters = {row.key: row for row in bundle.characters}
    facts = {row.key: row for row in bundle.facts}
    player = characters["player"]

    for lead_key, relationship_fixture in test.fixtures.relationships.items():
        lead = characters[lead_key]
        relationship = next(
            (
                row
                for row in bundle.relationships
                if row.character_a_id == lead.id and row.character_b_id == player.id
            ),
            None,
        )
        if relationship is None:
            relationship = Relationship(
                world_id=bundle.world.id,
                character_a_id=lead.id,
                character_b_id=player.id,
            )
            bundle.relationships.append(relationship)
        for key, value in relationship_fixture.model_dump(
            exclude_none=True, exclude_defaults=True
        ).items():
            setattr(relationship, key, value)

    for actor_key, fixture_facts in test.fixtures.knowledge.items():
        actor = characters[actor_key]
        for fact_key, state in fixture_facts.items():
            fact = facts[fact_key]
            row = next(
                (
                    item
                    for item in bundle.knowledge
                    if item.character_id == actor.id and item.fact_id == fact.id
                ),
                None,
            )
            if row is None:
                bundle.knowledge.append(
                    CharacterKnowledge(
                        character_id=actor.id,
                        fact_id=fact.id,
                        knowledge_state=KnowledgeState(state),
                        confidence=1.0,
                        source=KnowledgeSource.SEED,
                    )
                )
            else:
                row.knowledge_state = KnowledgeState(state)
                row.confidence = 1.0

    quests = {row.key: row for row in bundle.quests}
    for quest_key, status in test.fixtures.quests.items():
        quests[quest_key].status = QuestStatus(status)
    threads = {row.key: row for row in bundle.plot_threads}
    for thread_key, thread_fixture in test.fixtures.plot_threads.items():
        thread = threads[thread_key]
        if thread_fixture.status is not None:
            thread.status = ThreadStatus(thread_fixture.status)
        if thread_fixture.stage is not None:
            thread.stage = thread_fixture.stage


def _resolve_path(snapshot: dict[str, Any], path: str) -> Any:
    current: Any = snapshot
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _assertion_result(assertion: AuthorAssertion, snapshot: dict[str, Any]) -> AssertionResult:
    actual = _resolve_path(snapshot, assertion.path)
    expected = assertion.expected
    try:
        if assertion.op == "exists":
            passed = actual is not _MISSING
        elif assertion.op == "not_exists":
            passed = actual is _MISSING
        elif actual is _MISSING:
            passed = False
        elif assertion.op == "eq":
            passed = actual == expected
        elif assertion.op == "ne":
            passed = actual != expected
        elif assertion.op == "gt":
            passed = actual > expected
        elif assertion.op == "gte":
            passed = actual >= expected
        elif assertion.op == "lt":
            passed = actual < expected
        elif assertion.op == "lte":
            passed = actual <= expected
        elif assertion.op == "contains":
            passed = expected in actual
        else:
            passed = expected not in actual
    except (TypeError, ValueError):
        passed = False
    public_actual = None if actual is _MISSING else actual
    return AssertionResult(
        path=assertion.path,
        op=assertion.op,
        passed=passed,
        expected=expected,
        actual=public_actual,
        message="" if passed else f"{assertion.path} {assertion.op} assertion failed",
    )


async def _snapshot(
    uow: MemoryUnitOfWork,
    package: ContentPackageV2,
    pack: ContentPack,
    bundle: SeedBundle,
    last_turn: TurnResult | None,
) -> dict[str, Any]:
    assert bundle.session is not None
    state = await build_world_state(uow, pack, bundle.world.id, bundle.session.player_character_id)
    characters = {row.id: row for row in await uow.characters.list_for_world(bundle.world.id)}
    character_keys = {row.id: row.key for row in characters.values()}
    facts = dict(uow.store.facts)
    relationships: dict[str, dict[str, Any]] = {}
    for character in characters.values():
        if character.key == "player":
            continue
        relation = await uow.relationships.get(character.id, state.player.id)
        relation = relation or await uow.relationships.get(state.player.id, character.id)
        relationships[character.key] = (
            {**relation.as_dict(), "tags": list(relation.tags)}
            if relation is not None
            else {"exists": False}
        )
    knowledge: dict[str, dict[str, str]] = {
        key: {fact.key: "UNKNOWN" for fact in facts.values()} for key in character_keys.values()
    }
    for row in uow.store.knowledge.values():
        actor_key = character_keys.get(row.character_id)
        fact = facts.get(row.fact_id)
        if actor_key and fact:
            knowledge[actor_key][fact.key] = str(row.knowledge_state)
    ending_context = await build_ending_context(uow, state, package.content.endings)
    endings = {
        row.key: {
            "available": row.available,
            "type": row.type,
            "lead": row.lead,
            "requires_consent": row.requires_consent,
        }
        for row in evaluate_endings(package.content.endings, ending_context)
    }
    locations = {row.id: row.key for row in bundle.locations}
    return {
        "world": {
            "current_minute": state.world.current_minute,
            "tension": state.world.narrative_tension,
        },
        "player": {
            "name": state.player.name,
            "age": state.player.age,
            "location": locations.get(state.player.location_id or "", ""),
            "attributes": state.player.attributes,
            "resources": state.player.resources,
            "progressions": state.player.progressions,
            "properties": state.player.properties,
        },
        "characters": {
            row.key: {
                "location": locations.get(row.location_id or "", ""),
                "alive": row.alive,
                "age": row.age,
            }
            for row in characters.values()
        },
        "relationships": relationships,
        "knowledge": knowledge,
        "quests": {row.key: {"status": str(row.status)} for row in state.active_quests},
        "plot_threads": {
            row.key: {"status": str(row.status), "stage": row.stage} for row in state.plot_threads
        },
        "endings": endings,
        "events": {
            "count": len(uow.store.events),
            "types": [row.event_type for row in uow.store.events],
        },
        "last_turn": (
            {
                "turn_number": last_turn.turn_number,
                "status": str(last_turn.status),
                "steps": last_turn.steps,
                "degraded": last_turn.degraded,
                "rejected": last_turn.rejected,
                "choices": [choice.label for choice in last_turn.choices],
            }
            if last_turn is not None
            else {}
        ),
    }


async def _run_case(
    package: ContentPackageV2,
    test: AuthorTestCase,
    *,
    content_dir: str,
) -> AuthorTestResult:
    started = time.perf_counter()
    try:
        pack = content_pack_from_v2(
            package,
            content_dir=content_dir,
            scenario_key=test.scenario or package.manifest.entry_scenario,
        )
        player = test.player
        bundle = build_world(
            pack,
            world_seed=f"author-test-{test.key}",
            player=PlayerSpec(
                name=player.name,
                age=player.age,
                gender=player.gender,
                background=player.background,
                attributes=player.attributes,
                resources=player.resources,
                progressions=player.progressions,
                properties=player.properties,
            ),
            session_seed=f"author-test-session-{test.key}",
        )
        assert bundle.session is not None
        _apply_fixtures(bundle, test)
        store = MemoryStore()
        store.load(bundle)
        uow = MemoryUnitOfWork(store)
        prompt_dir = str(getattr(prompts, "__path__", [""])[0])
        orchestrator = build_orchestrator(
            settings=Settings(
                app_env="test",
                llm_provider="null",
                debug_mode=False,
                embedding_backend="hash",
                embedding_dim=128,
                content_dir=content_dir,
                content_pack=package.manifest.key,
                prompts_dir=prompt_dir,
            ),
            pack=pack,
        )
        last_turn: TurnResult | None = None
        for index, action in enumerate(test.actions, start=1):
            last_turn = await orchestrator.advance(
                uow,
                TurnRequest(
                    session_id=bundle.session.id,
                    text=action.text,
                    idempotency_key=f"author-test-{test.key}-{index}",
                    narrative_max_chars=action.narrative_max_chars,
                ),
            )
        snapshot = await _snapshot(uow, package, pack, bundle, last_turn)
        assertions = [_assertion_result(row, snapshot) for row in test.assertions]
        passed = all(row.passed for row in assertions)
        return AuthorTestResult(
            key=test.key,
            name=test.name,
            passed=passed,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            actions_run=len(test.actions),
            assertions=assertions,
        )
    except Exception as exc:
        return AuthorTestResult(
            key=test.key,
            name=test.name,
            passed=False,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            actions_run=0,
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_author_tests(
    package: ContentPackageV2,
    *,
    content_dir: str = ".",
) -> AuthorTestSuiteResult:
    """Run bounded, no-network author tests in isolated in-memory worlds."""
    started = time.perf_counter()
    declared = list(package.author_tests)
    tests = declared or [_built_in_smoke(package)]
    action_count = sum(len(test.actions) for test in tests)
    if action_count > MAX_SUITE_ACTIONS:
        result = AuthorTestResult(
            key="suite_execution_budget",
            name="Author test suite execution budget",
            passed=False,
            duration_ms=0,
            actions_run=0,
            error=(
                f"suite declares {action_count} actions; maximum is {MAX_SUITE_ACTIONS}"
            ),
        )
        return AuthorTestSuiteResult(
            passed=False,
            declared_tests=len(declared),
            total=1,
            passed_count=0,
            failed_count=1,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            results=[result],
        )
    results = [await _run_case(package, test, content_dir=content_dir) for test in tests]
    passed_count = sum(result.passed for result in results)
    return AuthorTestSuiteResult(
        passed=passed_count == len(results),
        declared_tests=len(declared),
        total=len(results),
        passed_count=passed_count,
        failed_count=len(results) - passed_count,
        duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
        results=results,
    )

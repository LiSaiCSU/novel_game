from __future__ import annotations

import json

import pytest

from apps.author_cli import run
from apps.authoring.templates import build_project_template, project_template_keys
from apps.authoring.testing import run_author_tests
from engine.contentpack.compiler import compile_package
from engine.contentpack.runtime_v2 import content_pack_from_v2
from engine.contentpack.schema_v2 import AuthorTestCase
from engine.world.seeder import PlayerSpec, build_world


def test_all_project_templates_compile_and_seed_a_playthrough() -> None:
    assert project_template_keys() == ("blank", "relationship_drama", "mystery")
    for template_key in project_template_keys():
        package = build_project_template(
            template_key,
            title="模板测试",
            slug="template-test",
            summary="一个经过编译器验证的起点。",
        )
        release = compile_package(package)
        runtime = content_pack_from_v2(package, content_dir=".")
        bundle = build_world(runtime, player=PlayerSpec(name="测试玩家"))
        assert len(release.checksum) == 64
        assert bundle.session is not None
        assert bundle.locations
        assert bundle.character_by_key("player") is not None


@pytest.mark.asyncio
async def test_all_project_template_author_tests_pass() -> None:
    for template_key in project_template_keys():
        package = build_project_template(
            template_key,
            title="Template tests",
            slug="template-tests",
        )
        suite = await run_author_tests(package)

        assert suite.declared_tests > 0
        assert suite.passed, suite.model_dump(mode="json")


@pytest.mark.asyncio
async def test_author_tests_report_assertion_failures_without_leaking_prose() -> None:
    package = build_project_template("blank", title="Failure", slug="failure-test")
    package.author_tests[0].assertions[0].expected = "wrong_location"

    suite = await run_author_tests(package)

    assert not suite.passed
    failure = suite.results[0].assertions[0]
    assert failure.actual == "opening_scene"
    assert failure.expected == "wrong_location"
    assert "narrative" not in suite.model_dump_json()


@pytest.mark.asyncio
async def test_author_test_can_execute_a_full_deterministic_turn() -> None:
    package = build_project_template("blank", title="Action", slug="action-test")
    package.author_tests = [
        AuthorTestCase.model_validate(
            {
                "key": "one_turn",
                "name": "A player action advances exactly one turn",
                "actions": [{"text": "观察周围"}],
                "assertions": [
                    {"path": "last_turn.turn_number", "op": "eq", "expected": 1},
                    {"path": "last_turn.status", "op": "eq", "expected": "COMPLETED"},
                ],
            }
        )
    ]

    suite = await run_author_tests(package)

    assert suite.passed, suite.model_dump(mode="json")
    assert suite.results[0].actions_run == 1


def test_author_cli_init_validate_test_and_compile(tmp_path) -> None:
    project = tmp_path / "story"
    assert (
        run(
            [
                "init",
                str(project),
                "--template",
                "mystery",
                "--title",
                "雾中来信",
                "--slug",
                "letters-in-fog",
                "--summary",
                "每个人记得的闭馆时间都不同。",
            ]
        )
        == 0
    )
    assert run(["validate", str(project), "--json"]) == 0
    assert run(["test", str(project), "--json"]) == 0
    assert run(["compile", str(project)]) == 0
    artifact = json.loads((project / "release.compiled.json").read_text(encoding="utf-8"))
    assert artifact["manifest"]["slug"] == "letters-in-fog"
    assert len(artifact["checksum"]) == 64


def test_author_cli_never_overwrites_a_nonempty_project(tmp_path) -> None:
    project = tmp_path / "existing"
    project.mkdir()
    marker = project / "keep.txt"
    marker.write_text("mine", encoding="utf-8")
    assert (
        run(
            [
                "init",
                str(project),
                "--title",
                "不能覆盖",
                "--slug",
                "do-not-overwrite",
            ]
        )
        == 2
    )
    assert marker.read_text(encoding="utf-8") == "mine"

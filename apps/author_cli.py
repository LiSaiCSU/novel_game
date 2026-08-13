"""Command-line authoring kit for Content Pack v2 projects."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from apps.authoring.templates import (
    build_project_template,
    list_project_templates,
    project_template_keys,
)
from apps.authoring.testing import AuthorTestSuiteResult, run_author_tests
from engine.contentpack.compiler import (
    compile_package,
    load_author_package,
    write_compiled_release,
)
from engine.contentpack.schema_v2 import ContentPackageV2
from engine.core.errors import EngineError

PACKAGE_NAMES = ("content-pack.yaml", "content-pack.yml", "content-pack.json")


def _source_path(value: str) -> Path:
    source = Path(value)
    if source.is_dir():
        for name in PACKAGE_NAMES:
            candidate = source / name
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(f"{source} does not contain " + ", ".join(PACKAGE_NAMES))
    if not source.is_file():
        raise FileNotFoundError(str(source))
    return source


def _package_counts(package: ContentPackageV2) -> dict[str, int]:
    content = package.content
    return {
        "scenarios": len(content.scenarios),
        "locations": len(content.locations),
        "characters": len(content.characters),
        "facts": len(content.facts),
        "quests": len(content.quests),
        "plot_threads": len(content.plot_threads),
        "rules": len(content.rules),
        "endings": len(content.endings),
        "author_tests": len(package.author_tests),
    }


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _templates(_args: argparse.Namespace) -> int:
    for template in list_project_templates():
        tags = " / ".join(template["genre_tags"])
        print(f"{template['key']:<20} {template['title']}  [{tags}]")
        print(f"  {template['description']}")
    return 0


def _init(args: argparse.Namespace) -> int:
    target = Path(args.directory).resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        print(f"error: target directory is not empty: {target}", file=sys.stderr)
        return 2
    package = build_project_template(
        args.template,
        title=args.title,
        slug=args.slug,
        summary=args.summary,
        locale=args.locale,
        rating=args.rating,
    )
    target.mkdir(parents=True, exist_ok=True)
    package_path = target / "content-pack.yaml"
    schema_path = target / "content-pack.schema.json"
    package_path.write_text(
        yaml.safe_dump(
            package.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
            width=100,
        ),
        encoding="utf-8",
    )
    schema_path.write_text(
        json.dumps(ContentPackageV2.model_json_schema(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"created {package_path}")
    print(f"schema  {schema_path}")
    print("next    narrative validate " + str(target))
    return 0


def _validate(args: argparse.Namespace) -> int:
    source = _source_path(args.path)
    package = load_author_package(source)
    release = compile_package(package)
    counts = _package_counts(package)
    result: dict[str, Any] = {
        "status": "valid",
        "path": str(source.resolve()),
        "schema_version": package.manifest.schema_version,
        "engine_api": package.manifest.engine.api_version,
        "checksum": release.checksum,
        "counts": counts,
    }
    if args.json:
        _print_json(result)
    else:
        print(f"valid    {source}")
        print(f"checksum {release.checksum}")
        print("content  " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


def _compile(args: argparse.Namespace) -> int:
    source = _source_path(args.path)
    package = load_author_package(source)
    release = compile_package(package)
    suite = asyncio.run(run_author_tests(package, content_dir=str(source.parent)))
    if not suite.passed:
        raise ValueError(
            f"author tests failed: {suite.failed_count}/{suite.total}; run narrative test for details"
        )
    output = Path(args.output) if args.output else source.with_name("release.compiled.json")
    write_compiled_release(release, output)
    print(f"compiled {output.resolve()}")
    print(f"checksum {release.checksum}")
    return 0


def _test(args: argparse.Namespace) -> int:
    source = _source_path(args.path)
    package = load_author_package(source)
    release = compile_package(package)
    suite: AuthorTestSuiteResult = asyncio.run(
        run_author_tests(package, content_dir=str(source.parent))
    )
    if args.require_declared and suite.declared_tests == 0:
        suite.passed = False
    result: dict[str, Any] = {
        "status": "passed" if suite.passed else "failed",
        "checksum": release.checksum,
        "suite": suite.model_dump(mode="json"),
    }
    if args.json:
        _print_json(result)
    else:
        print(f"{result['status']:<8} {source}")
        print(
            f"tests    {suite.passed_count}/{suite.total} passed "
            f"({suite.duration_ms} ms, {suite.declared_tests} declared)"
        )
        for case in suite.results:
            marker = "PASS" if case.passed else "FAIL"
            print(f"  {marker:<4} {case.key}: {case.name}")
            if case.error:
                print(f"       {case.error}")
            for assertion in case.assertions:
                if not assertion.passed:
                    print(
                        f"       {assertion.path} {assertion.op}: "
                        f"expected={assertion.expected!r}, actual={assertion.actual!r}"
                    )
        if args.require_declared and suite.declared_tests == 0:
            print("  FAIL no author-declared tests (built-in smoke test is not sufficient)")
    return 0 if suite.passed else 1


def _schema(args: argparse.Namespace) -> int:
    payload = json.dumps(ContentPackageV2.model_json_schema(), ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        print(f"schema {output.resolve()}")
    else:
        print(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="narrative",
        description="Content Pack v2 authoring kit",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    templates = commands.add_parser("templates", help="list curated starter projects")
    templates.set_defaults(handler=_templates)

    init = commands.add_parser("init", help="create a compiler-verified starter project")
    init.add_argument("directory")
    init.add_argument("--template", choices=project_template_keys(), default="relationship_drama")
    init.add_argument("--title", required=True)
    init.add_argument("--slug", required=True)
    init.add_argument("--summary", default="")
    init.add_argument("--locale", default="zh-CN")
    init.add_argument("--rating", choices=("all", "13+", "16+", "18+"), default="16+")
    init.set_defaults(handler=_init)

    validate = commands.add_parser("validate", help="validate schema, references and rules")
    validate.add_argument("path")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=_validate)

    compile_command = commands.add_parser("compile", help="build an immutable release artifact")
    compile_command.add_argument("path")
    compile_command.add_argument("--output", "-o")
    compile_command.set_defaults(handler=_compile)

    test = commands.add_parser("test", help="run deterministic author-declared gameplay tests")
    test.add_argument("path")
    test.add_argument(
        "--require-declared",
        action="store_true",
        help="fail when the package only has the built-in seed smoke test",
    )
    test.add_argument("--json", action="store_true")
    test.set_defaults(handler=_test)

    schema = commands.add_parser("schema", help="print or write the v2 JSON Schema")
    schema.add_argument("--output", "-o")
    schema.set_defaults(handler=_schema)
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (EngineError, ValidationError, FileNotFoundError, ValueError) as exc:
        if isinstance(exc, EngineError):
            detail = exc.to_dict()
        elif isinstance(exc, ValidationError):
            detail = {"code": "SCHEMA_VALIDATION_ERROR", "errors": exc.errors()}
        else:
            detail = {"code": type(exc).__name__.upper(), "message": str(exc)}
        print(json.dumps(detail, ensure_ascii=False, indent=2, default=str), file=sys.stderr)
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())

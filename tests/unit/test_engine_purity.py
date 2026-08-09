"""Architecture guards (DECISIONS D-004, D-006, D-008; Prompt sections 48, 65, 75).

These are the tests that keep "Engine does not know it is running a cultivation
game" true as the codebase grows. They read the source, not the behaviour.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE = REPO_ROOT / "engine"
CJK = re.compile(r"[一-鿿]")


def engine_files() -> list[Path]:
    return sorted(p for p in ENGINE.rglob("*.py") if p.name != "__init__.py")


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def docstring_nodes(tree: ast.Module) -> set[int]:
    """ids() of the string constants that are docstrings, so we can skip them."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


@pytest.mark.parametrize("path", engine_files(), ids=lambda p: str(p.relative_to(ENGINE)))
def test_engine_does_not_depend_on_infrastructure(path: Path) -> None:
    """engine/ is a pure domain layer: no ORM, no web framework, no adapters."""
    forbidden = ("sqlalchemy", "alembic", "fastapi", "starlette", "database", "apps", "redis")
    modules = imported_modules(parse(path))
    offending = [m for m in modules if m.split(".")[0] in forbidden]
    assert not offending, f"{path.relative_to(REPO_ROOT)} imports {offending}"


@pytest.mark.parametrize("path", engine_files(), ids=lambda p: str(p.relative_to(ENGINE)))
def test_randomness_only_flows_through_game_rng(path: Path) -> None:
    """Prompt section 9: no ad-hoc random calls scattered across modules."""
    if path.parent.name == "rng":
        return
    modules = imported_modules(parse(path))
    assert "random" not in modules, f"{path.relative_to(REPO_ROOT)} imports random directly"
    source = path.read_text(encoding="utf-8")
    assert "np.random" not in source and "numpy.random" not in source


@pytest.mark.parametrize("path", engine_files(), ids=lambda p: str(p.relative_to(ENGINE)))
def test_engine_contains_no_content_pack_language(path: Path) -> None:
    """No lore literals in the engine - all world text comes from content/."""
    tree = parse(path)
    skip = docstring_nodes(tree)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in skip:
                continue
            if CJK.search(node.value):
                offenders.append(node.value[:40])
    assert not offenders, f"{path.relative_to(REPO_ROOT)} hardcodes world text: {offenders}"


@pytest.mark.parametrize("path", engine_files(), ids=lambda p: str(p.relative_to(ENGINE)))
def test_no_hardcoded_model_names(path: Path) -> None:
    """Prompt section 48: model identifiers live in .env, never in source."""
    source = path.read_text(encoding="utf-8")
    patterns = [
        r"claude-[a-z0-9.\-]+",
        r"gpt-[0-9][a-z0-9.\-]*",
        r"\bo[134]-(mini|preview)\b",
        r"gemini-[a-z0-9.\-]+",
        r"deepseek-[a-z0-9.\-]+",
        r"qwen[0-9]?-[a-z0-9.\-]+",
    ]
    for pattern in patterns:
        found = re.findall(pattern, source, flags=re.IGNORECASE)
        assert not found, f"{path.relative_to(REPO_ROOT)} hardcodes model name(s) {found}"


def test_only_mutations_module_constructs_state_changes() -> None:
    """Prompt section 18: AI-facing modules cannot mint StateChange objects."""
    ai_modules = ("narrative", "director", "characters", "context", "llm")
    for name in ai_modules:
        folder = ENGINE / name
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.py"):
            tree = parse(path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id != "StateChange", (
                        f"{path.relative_to(REPO_ROOT)} builds a StateChange directly; "
                        "go through engine.core.mutations constructors"
                    )


def test_engine_never_writes_through_a_repository() -> None:
    """AI subsystems propose; only the orchestrator's transaction commits."""
    banned_calls = {"apply", "commit", "append"}
    for name in ("narrative", "director", "context"):
        folder = ENGINE / name
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.py"):
            tree = parse(path)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in banned_calls
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr in ("events", "characters", "memories", "turns")
                ):
                    pytest.fail(
                        f"{path.relative_to(REPO_ROOT)} writes through a repository directly"
                    )

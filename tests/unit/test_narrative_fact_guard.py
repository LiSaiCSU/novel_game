from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from engine.contentpack.pack import load_content_pack
from engine.narrative.fact_guard import NarrativeFactGuard


def _guard_and_state() -> tuple[NarrativeFactGuard, SimpleNamespace]:
    root = Path(__file__).resolve().parents[2]
    pack = load_content_pack(root / "content", "campus_romance_v1")
    state = SimpleNamespace(
        inventory=[SimpleNamespace(item_key="unfinished_letter", quantity=1)]
    )
    return NarrativeFactGuard(pack), state


def test_declared_item_facts_accept_equivalent_spacing() -> None:
    guard, state = _guard_and_state()

    violations = guard.review(
        state,
        player_action="仔细阅读未完成信",
        prose="邮戳日期是2006年4月6日，收件地址只写了月见馆。",
    )

    assert violations == []


def test_declared_item_facts_reject_omission_and_contradiction() -> None:
    guard, state = _guard_and_state()

    violations = guard.review(
        state,
        player_action="仔细阅读那封信",
        prose="邮戳糊成一团，只能看清年份。信寄往月见馆。",
    )

    assert {(item.kind, item.value) for item in violations} == {
        ("missing_required", "2006 年 4 月 6 日"),
        ("forbidden_present", "邮戳糊"),
    }


def test_constraints_do_not_apply_when_item_was_not_referenced() -> None:
    guard, state = _guard_and_state()

    assert guard.review(state, player_action="看看窗外", prose="天色很亮。") == []

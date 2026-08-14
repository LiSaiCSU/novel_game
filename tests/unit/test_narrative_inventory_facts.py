from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from engine.contentpack.pack import load_content_pack
from engine.context.builder import ContextBuilder


def test_inventory_context_exposes_only_author_approved_narrative_facts() -> None:
    root = Path(__file__).resolve().parents[2]
    pack = load_content_pack(root / "content", "campus_romance_v1")
    builder = object.__new__(ContextBuilder)
    builder.pack = pack
    state = SimpleNamespace(
        inventory=[SimpleNamespace(item_key="unfinished_letter", quantity=1)]
    )

    rendered = builder._inventory_facts(state)

    assert "2006 年 4 月 6 日" in rendered
    assert "没有个人姓名" in rendered
    assert "写信人与收件人身份都未知" in rendered
    assert "fact_letter_exists" not in rendered
    assert "quest_item" not in rendered


def test_inventory_context_does_not_turn_currency_balance_into_a_prop() -> None:
    root = Path(__file__).resolve().parents[2]
    pack = load_content_pack(root / "content", "campus_romance_v1")
    builder = object.__new__(ContextBuilder)
    builder.pack = pack
    state = SimpleNamespace(inventory=[SimpleNamespace(item_key="yen", quantity=5_000)])

    assert builder._inventory_facts(state) == "-"

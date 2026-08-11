"""The content pack selects a canonical adult co-protagonist per playthrough."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from engine.core.ids import PLAYER_KEY
from engine.narrative.style import NarrativeStyle
from engine.orchestrator.turn import TurnRequest
from engine.world.seeder import PlayerSpec, build_world


@pytest.mark.parametrize(
    ("gender", "expected_lead"),
    [("male", "lin_qingxue"), ("female", "zhao_wuji")],
)
def test_player_gender_selects_one_canonical_story_lead(
    pack, gender: str, expected_lead: str
) -> None:
    bundle = build_world(
        pack,
        world_seed=f"story-{gender}",
        player=PlayerSpec(name="测试者", gender=gender, age=22),
    )
    player = bundle.character_by_key(PLAYER_KEY)
    lead = bundle.character_by_key(expected_lead)
    assert player is not None and lead is not None

    assert player.metadata["story_lead_key"] == expected_lead
    assert lead.metadata["story_role"] == "co_protagonist"
    assert lead.metadata["paired_player_id"] == player.id
    assert lead.location_id == player.location_id
    assert lead.goal_lifecycle is not None
    assert lead.goal_lifecycle.goal == lead.long_term_goal
    assert lead.goal_lifecycle.action_interval_minutes == 1440
    assert len(lead.goal_lifecycle.steps) >= 2

    pair = [
        relation
        for relation in bundle.relationships
        if {relation.character_a_id, relation.character_b_id} == {player.id, lead.id}
    ]
    assert len(pair) == 2
    assert all("co_protagonist" in relation.tags for relation in pair)
    assert all("romance_candidate" in relation.tags for relation in pair)


def test_story_clue_is_inventory_and_player_knowledge_not_opening_invention(pack) -> None:
    bundle = build_world(
        pack,
        world_seed="story-clue",
        player=PlayerSpec(name="测试者", gender="male", age=22),
    )
    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    assert any(
        row.character_id == player.id and row.item_key == "blood_roster_fragment"
        for row in bundle.inventory
    )
    fact = next(f for f in bundle.facts if f.key == "fact_player_named_as_sacrifice")
    assert any(
        row.character_id == player.id and row.fact_id == fact.id
        for row in bundle.knowledge
    )


def test_narrative_length_is_bounded_and_trimmed_at_a_chinese_sentence(pack) -> None:
    style = NarrativeStyle(pack)
    assert style.as_prompt_vars(1200)["max_length"] == "1200"
    prose = "甲" * 450 + "。" + "乙" * 300
    trimmed = style.enforce_max_chars(prose, 500)
    assert len(trimmed) <= 500
    assert trimmed.endswith("。")

    with pytest.raises(ValidationError):
        TurnRequest(session_id="s", text="继续", narrative_max_chars=399)
    with pytest.raises(ValidationError):
        TurnRequest(session_id="s", text="继续", narrative_max_chars=4001)

"""The world grows to meet the player - within limits the code enforces.

The steward is the answer to "干什么都不可以": a player who reaches for
something the content pack never wrote down should find it there, not be told
they were wrong to ask. What the model may *propose* is wide open; what may
actually exist is decided here, in Python.
"""

from __future__ import annotations

import pytest

from engine.core.mutations import ChangeKind
from engine.core.types import CharacterType
from engine.world.state_view import WorldStateView
from engine.world.steward import (
    CharacterDraft,
    LocationDraft,
    StewardPlan,
    StewardResult,
    WorldSteward,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def steward(pack) -> WorldSteward:
    return WorldSteward(pack)


async def world_characters(uow, state: WorldStateView):
    return await uow.characters.list_for_world(state.world.id)


# ---------------------------------------------------------------- recognition
async def test_a_nickname_resolves_to_the_place_that_already_exists(
    steward: WorldSteward, state: WorldStateView
) -> None:
    """"大殿" is 青云主殿. Inventing a second one would corrupt the world."""
    hit = steward.recognise_location(state, "大殿")
    assert hit is not None and hit.key == "qingyun_main_hall"


async def test_a_partial_name_resolves_to_the_nearest_match(
    steward: WorldSteward, state: WorldStateView
) -> None:
    hit = steward.recognise_location(state, "药铺")
    assert hit is not None and hit.key == "herb_shop"


async def test_recognition_reaches_characters_who_are_not_in_the_room(
    steward: WorldSteward, state: WorldStateView, uow
) -> None:
    everyone = await world_characters(uow, state)
    absent = next(
        c for c in everyone if c.alive and c not in state.present_characters
    )
    hit = steward.recognise_character(state, absent.name, everyone)
    assert hit is not None and hit.key == absent.key


async def test_recognition_returns_nothing_for_something_genuinely_absent(
    steward: WorldSteward, state: WorldStateView, uow
) -> None:
    everyone = await world_characters(uow, state)
    assert steward.recognise_location(state, "北冥雪原") is None
    assert steward.recognise_character(state, "卖糖葫芦的老头", everyone) is None


# ---------------------------------------------------------------- creation
async def test_an_absent_shopkeeper_is_created_and_becomes_real(
    steward: WorldSteward, state: WorldStateView, uow
) -> None:
    everyone = await world_characters(uow, state)
    result = StewardResult()
    plan = StewardPlan(
        interpretation="玩家想找药铺掌柜攀谈",
        target_key="baicao_shopkeeper",
        new_characters=[
            CharacterDraft(
                key="baicao_shopkeeper",
                name="孙半夏",
                title="百草堂掌柜",
                age=54,
                location_key="herb_shop",
                speech_style="慢条斯理，从不把话说满",
            )
        ],
    )
    steward._apply_plan(state, plan, everyone, result)

    assert [c.name for c in result.new_characters] == ["孙半夏"]
    assert result.target_key == "baicao_shopkeeper"
    spawned = result.new_characters[0]
    assert spawned.location_key == "herb_shop"
    # One change, in the same set as everything else the turn commits.
    assert [c.kind for c in result.changes] == [ChangeKind.CHARACTER_SPAWN]


async def test_invented_people_are_supporting_cast_only(
    steward: WorldSteward, state: WorldStateView, uow
) -> None:
    """An improvised extra must never be able to overshadow the written cast."""
    everyone = await world_characters(uow, state)
    result = StewardResult()
    top_realm = steward.pack.realms.realms[-1].key
    plan = StewardPlan(
        new_characters=[
            CharacterDraft(
                key="hidden_grandmaster",
                name="无名老者",
                realm=top_realm,
                location_key=state.location_key(),
            )
        ]
    )
    steward._apply_plan(state, plan, everyone, result)

    spawned = result.new_characters[0]
    ladder = steward.pack.realms
    assert spawned.character_type is CharacterType.MINOR_NPC
    assert ladder.order(spawned.realm) <= ladder.order(state.player.realm) + 1
    assert any("realm_capped" in note for note in result.notes)


async def test_a_new_place_hangs_off_a_real_one_and_cannot_out_danger_it(
    steward: WorldSteward, state: WorldStateView, uow
) -> None:
    everyone = await world_characters(uow, state)
    result = StewardResult()
    parent = state.graph.by_key("qingyun_market")
    assert parent is not None
    plan = StewardPlan(
        location_key="back_alley",
        new_locations=[
            LocationDraft(
                key="back_alley",
                name="坊市后巷",
                parent_key="qingyun_market",
                danger_level=99,
                travel_minutes_from_parent=100000,
            )
        ],
    )
    steward._apply_plan(state, plan, everyone, result)

    spawned = result.new_locations[0]
    assert spawned.parent_id == parent.id
    assert spawned.danger_level <= parent.danger_level + 1
    assert 1 <= spawned.travel_minutes[parent.key] <= 240
    assert result.location_key == "back_alley"
    assert [c.kind for c in result.changes] == [ChangeKind.LOCATION_SPAWN]


async def test_a_proposal_may_not_reuse_an_existing_key(
    steward: WorldSteward, state: WorldStateView, uow
) -> None:
    everyone = await world_characters(uow, state)
    result = StewardResult()
    plan = StewardPlan(
        new_locations=[
            LocationDraft(key="herb_shop", name="冒牌百草堂", parent_key="qingyun_market")
        ]
    )
    steward._apply_plan(state, plan, everyone, result)

    assert not result.new_locations
    assert "steward_location_key_taken:herb_shop" in result.notes


async def test_creation_per_turn_is_capped(
    steward: WorldSteward, state: WorldStateView, uow
) -> None:
    everyone = await world_characters(uow, state)
    result = StewardResult()
    plan = StewardPlan(
        new_characters=[
            CharacterDraft(
                key=f"extra_{i}", name=f"路人{i}", location_key=state.location_key()
            )
            for i in range(9)
        ]
    )
    steward._apply_plan(state, plan, everyone, result)

    assert len(result.new_characters) == 3


async def test_a_spawned_character_survives_a_round_trip_through_the_store(
    steward: WorldSteward, state: WorldStateView, uow, store
) -> None:
    """Created once, remembered forever: that is what makes it real."""
    from engine.core.mutations import ChangeSet

    everyone = await world_characters(uow, state)
    result = StewardResult()
    steward._apply_plan(
        state,
        StewardPlan(
            new_characters=[
                CharacterDraft(
                    key="stall_keeper",
                    name="周老三",
                    location_key=state.location_key(),
                )
            ]
        ),
        everyone,
        result,
    )

    change_set = ChangeSet()
    change_set.extend(result.changes)
    await uow.apply(change_set)
    await uow.commit()

    reloaded = await uow.characters.list_for_world(state.world.id)
    assert any(c.key == "stall_keeper" and c.name == "周老三" for c in reloaded)

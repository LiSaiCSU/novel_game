"""Content pack loading and validation."""

from __future__ import annotations

import pytest

from engine.contentpack.pack import ContentPack


def test_pack_loads(pack: ContentPack) -> None:
    assert pack.key == "cultivation_v1"
    assert pack.name
    assert pack.locations and pack.characters and pack.items and pack.skills


def test_realm_ladder_is_ordered(pack: ContentPack) -> None:
    orders = [r.order for r in pack.realms.realms]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)


def test_realm_comparison(pack: ContentPack) -> None:
    ladder = pack.realms
    low = ladder.realms[1]  # first tier above mortal
    high = ladder.realms[2]
    assert ladder.compare(low.key, low.stages[0].key, high.key, high.stages[0].key) < 0
    assert ladder.compare(high.key, high.stages[0].key, low.key, low.stages[0].key) > 0
    assert ladder.compare(low.key, low.stages[0].key, low.key, low.stages[0].key) == 0


def test_realm_progression_walks_the_whole_ladder(pack: ContentPack) -> None:
    ladder = pack.realms
    realm, stage = ladder.realms[0].key, ladder.realms[0].stages[0].key
    seen = 0
    while True:
        step = ladder.next_step(realm, stage)
        if step is None:
            break
        realm, stage = step
        seen += 1
        assert seen < 200, "next_step() looped"
    assert realm == ladder.realms[-1].key
    assert seen >= 4


def test_realm_ladder_is_extensible(pack: ContentPack) -> None:
    """Adding tiers must be a content change, never a code change."""
    ladder = pack.realms
    top = ladder.realms[-1]
    assert top.order > 3, "the pack should already carry a tier beyond V1's playable range"
    assert ladder.power(top.key, top.stages[-1].key) > ladder.power(
        ladder.realms[0].key, ladder.realms[0].stages[0].key
    )


def test_every_referenced_entity_exists(pack: ContentPack) -> None:
    """load_content_pack validates on load; assert the guard is actually wired."""
    location_keys = {loc["key"] for loc in pack.locations}
    for character in pack.characters:
        if character.get("location"):
            assert character["location"] in location_keys


def test_validation_rejects_dangling_reference(tmp_path, pack: ContentPack) -> None:
    import shutil

    from engine.contentpack.pack import load_content_pack
    from engine.core.errors import ContentValidationError

    dest = tmp_path / "broken_v1"
    shutil.copytree(pack.root, dest)
    characters = dest / "characters.yaml"
    text = characters.read_text(encoding="utf-8")
    text = text.replace("location: qingyun_back_mountain", "location: nowhere_at_all", 1)
    characters.write_text(text, encoding="utf-8")

    with pytest.raises(ContentValidationError):
        load_content_pack(tmp_path, "broken_v1")


def test_rules_lookup_by_dotted_path(pack: ContentPack) -> None:
    assert isinstance(pack.rule("combat.hit_chance.base"), float)
    assert pack.rule("does.not.exist", "fallback") == "fallback"


def test_validation_rejects_invalid_scheduled_director_beat(
    tmp_path, pack: ContentPack
) -> None:
    import shutil

    from engine.contentpack.pack import load_content_pack
    from engine.core.errors import ContentValidationError

    dest = tmp_path / "broken_schedule"
    shutil.copytree(pack.root, dest)
    plot = dest / "plot_threads.yaml"
    text = plot.read_text(encoding="utf-8")
    text = text.replace("at_minutes_from_start: 129600", "at_minutes_from_start: -1", 1)
    plot.write_text(text, encoding="utf-8")

    with pytest.raises(ContentValidationError, match="failed validation"):
        load_content_pack(tmp_path, "broken_schedule")

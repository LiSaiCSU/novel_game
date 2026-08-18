"""Clocks have to survive the trip a real playthrough takes.

A playthrough is seeded from a compiled, immutable release - not from the
content directory. Anything that only exists on the directory loader is
invisible to every actual game, which is exactly how the first version of
this feature shipped: the dials were correct in a scratch check against
``load_content_pack`` and empty in production.
"""

from __future__ import annotations

from engine.contentpack.legacy_v2 import project_v1_as_v2
from engine.contentpack.runtime_v2 import content_pack_from_v2
from engine.world.seeder import PlayerSpec, build_world


def test_authored_clocks_reach_a_world_seeded_from_a_release(pack) -> None:
    from_directory = {clock["key"] for clock in pack.clocks}
    assert from_directory, "the fixture pack should author clocks"

    package = project_v1_as_v2(pack, slug="roundtrip", rating="16+", tags=["test"])
    republished = content_pack_from_v2(package, content_dir=pack.root)
    bundle = build_world(republished, world_seed="s", player=PlayerSpec(name="测试"))

    assert {clock.key for clock in bundle.clocks} == from_directory


def test_a_release_published_before_clocks_existed_still_loads(pack) -> None:
    package = project_v1_as_v2(pack, slug="legacy", rating="16+", tags=["test"])
    stripped = package.model_dump(mode="json")
    del stripped["content"]["clocks"]

    from engine.contentpack.schema_v2 import ContentPackageV2

    revalidated = ContentPackageV2.model_validate(stripped)
    republished = content_pack_from_v2(revalidated, content_dir=pack.root)
    bundle = build_world(republished, world_seed="s", player=PlayerSpec(name="测试"))

    assert bundle.clocks == []

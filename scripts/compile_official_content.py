"""Compile every bundled official pack as a CI/release gate without writing files."""

from __future__ import annotations

import asyncio

from apps.authoring.testing import run_author_tests
from engine.contentpack.compiler import compile_package
from engine.contentpack.legacy_v2 import project_v1_as_v2
from engine.contentpack.pack import load_content_pack
from engine.core.config import get_settings


async def compile_official_content() -> None:
    settings = get_settings()
    for key in (
        "cultivation_v1", "campus_romance_v1", "tomb_lantern_v1",
        "fog_harbor_v1", "spirit_pact_v1",
        "three_year_pact_v1", "second_chance_v1",
        "wedding_verdict_v1", "divorce_ledger_v1", "shelter_broadcast_v1",
        "seoul_blackout_v1", "zombie_station_v1", "war_radio_v1",
        "exiled_empress_v1", "jade_gate_expedition_v1", "room_404_v1",
        "jiangshi_courier_v1", "heartbeat_countdown_v1", "abyss_oxygen_v1",
        "live_court_v1",
    ):
        package = project_v1_as_v2(load_content_pack(settings.content_path, key))
        release = compile_package(package)
        suite = await run_author_tests(
            package,
            content_dir=str(settings.content_path / key),
        )
        if not suite.passed or suite.declared_tests == 0:
            raise RuntimeError(
                f"{key} author tests failed or are missing: {suite.model_dump(mode='json')}"
            )
        print(
            f"{key} {package.manifest.version} {release.checksum} "
            f"tests={suite.passed_count}/{suite.total}"
        )


def main() -> None:
    asyncio.run(compile_official_content())


if __name__ == "__main__":
    main()

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
    for key in ("cultivation_v1", "campus_romance_v1"):
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

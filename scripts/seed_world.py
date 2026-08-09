"""Create and persist a world from a content pack.

    python scripts/seed_world.py --player 沈砚 --seed demo-1
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from database.seeding import persist_bundle  # noqa: E402
from database.session import create_all, dispose, get_sessionmaker  # noqa: E402
from engine.contentpack.pack import load_content_pack  # noqa: E402
from engine.core.config import get_settings  # noqa: E402
from engine.core.ids import PLAYER_KEY  # noqa: E402
from engine.world.seeder import PlayerSpec, build_world  # noqa: E402


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    pack = load_content_pack(settings.content_path, args.pack or settings.content_pack)
    print(f"content pack : {pack.key} ({pack.name})")
    print(f"database     : {settings.database_url}")

    await create_all()

    player = PlayerSpec(name=args.player, gender=args.gender, age=args.age) if args.player else None
    bundle = build_world(pack, world_seed=args.seed, player=player)

    maker = get_sessionmaker()
    async with maker() as session:
        await persist_bundle(session, bundle)
        await session.commit()

    print(f"world id     : {bundle.world.id}")
    print(f"locations    : {len(bundle.locations)}")
    print(f"factions     : {len(bundle.factions)}")
    print(f"characters   : {len(bundle.characters)}")
    print(f"relationships: {len(bundle.relationships)}")
    print(f"facts        : {len(bundle.facts)}  (knowledge rows: {len(bundle.knowledge)})")
    print(f"plot threads : {len(bundle.plot_threads)}  quests: {len(bundle.quests)}")
    if bundle.session is not None:
        print(f"session id   : {bundle.session.id}")
        pc = bundle.character_by_key(PLAYER_KEY)
        if pc is not None:
            print(f"player       : {pc.name} / {pack.realms.display(pc.realm, pc.realm_stage)}")
    await dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a world from a content pack")
    parser.add_argument("--pack", default=None, help="content pack key")
    parser.add_argument("--seed", default=None, help="world seed")
    parser.add_argument("--player", default=None, help="create a player character with this name")
    parser.add_argument("--gender", default="unspecified")
    parser.add_argument("--age", type=int, default=18)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

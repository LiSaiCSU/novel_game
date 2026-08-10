"""Play the game in a terminal, entirely in memory.

Useful for exercising the engine without a database or a browser:

    python scripts/play_cli.py --name 沈砚
    python scripts/play_cli.py --name 沈砚 --script "我环顾四周" "我打坐修炼一个时辰"

Type ``/debug`` to dump the last turn's trace, ``/quit`` to leave.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from database.memory_uow import MemoryStore, MemoryUnitOfWork  # noqa: E402
from engine.contentpack.pack import load_content_pack  # noqa: E402
from engine.core.config import get_settings  # noqa: E402
from engine.orchestrator.factory import build_orchestrator  # noqa: E402
from engine.orchestrator.turn import TurnRequest  # noqa: E402
from engine.world.seeder import PlayerSpec, build_world  # noqa: E402
from engine.world.state_view import build_world_state  # noqa: E402

RULE = "-" * 68


def _print_beat(beat) -> None:
    """Show what the scene is waiting on, if it is waiting on anything."""
    if beat is None:
        return
    if beat.question:
        print(f"\n  {beat.question}")
    options = [o.label for o in beat.options if o.label]
    if options:
        print("  " + "   ".join(f"[{o}]" for o in options))
    elif not beat.needs_player:
        print("  [继续]")


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    pack = load_content_pack(settings.content_path, settings.content_pack)
    bundle = build_world(
        pack, world_seed=args.seed, player=PlayerSpec(name=args.name, age=args.age)
    )
    store = MemoryStore()
    store.load(bundle)
    uow = MemoryUnitOfWork(store)
    orchestrator = build_orchestrator(settings=settings, pack=pack)

    assert bundle.session is not None
    session_id = bundle.session.id

    print(RULE)
    print(f"{pack.name}  |  pack={pack.key}  provider={settings.llm_provider}")
    print(RULE)
    state = await build_world_state(
        uow, pack, bundle.world.id, bundle.session.player_character_id
    )
    prologue = await orchestrator.open_session(uow, bundle.session, state)
    print(prologue.text.strip() or (state.location.description if state.location else ""))
    _print_beat(prologue.beat)
    print(RULE)

    last_debug = None
    scripted = list(args.script or [])

    while True:
        if scripted:
            text = scripted.pop(0)
            print(f"\n> {text}")
        else:
            try:
                text = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
        if not text:
            continue
        if text in ("/quit", "/exit"):
            break
        if text == "/debug":
            print(json.dumps(last_debug, ensure_ascii=False, indent=2)[:6000] if last_debug else "(no trace yet)")
            continue

        result = await orchestrator.advance(
            uow, TurnRequest(session_id=session_id, text=text, debug=True)
        )
        last_debug = result.debug
        print()
        print(result.narrative)
        _print_beat(result.beat)
        changes = result.state_changes or {}
        if changes.get("character"):
            print(f"  变化: {json.dumps(changes['character'], ensure_ascii=False)}")
        minutes = changes.get("world_minute")
        if minutes and minutes[1] > minutes[0]:
            print(f"  时间: +{minutes[1] - minutes[0]} 分 -> {changes['time_label'][1]}")
        if result.debug:
            timings = result.debug.get("stage_timings", {})
            total = sum(timings.values())
            print(f"  [{total} ms, {len(result.debug.get('llm_calls', []))} LLM calls]")

    print("\n" + RULE)
    print(f"turns played: {store.sessions[session_id].turn_number}")
    print(f"events logged: {len(store.events)}")
    print(f"memories stored: {len(store.memories)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Play in the terminal")
    parser.add_argument("--name", default="无名", help="player character name")
    parser.add_argument("--age", type=int, default=18)
    parser.add_argument("--seed", default="cli-1")
    parser.add_argument("--script", nargs="*", help="run these inputs then exit")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

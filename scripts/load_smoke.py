"""Run the release/playthrough concurrency acceptance smoke against a live API.

The command intentionally creates test accounts and playthroughs. Point it at
an isolated staging deployment, not production.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
import uuid

import httpx


async def _timed_state(client: httpx.AsyncClient, playthrough_id: str) -> float:
    started = time.perf_counter()
    response = await client.get(f"/api/v1/playthroughs/{playthrough_id}/state")
    response.raise_for_status()
    return (time.perf_counter() - started) * 1000


async def run(args: argparse.Namespace) -> int:
    email = args.email or f"load-{uuid.uuid4().hex[:12]}@example.com"
    async with httpx.AsyncClient(
        base_url=args.base_url,
        timeout=args.timeout,
        trust_env=args.trust_env,
    ) as client:
        registered = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": args.password,
                "display_name": "并发验收",
            },
        )
        if registered.status_code not in {200, 201}:
            logged_in = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": args.password},
            )
            logged_in.raise_for_status()
        csrf = client.cookies.get("ng_csrf")
        if not csrf:
            raise RuntimeError("authentication did not issue a CSRF cookie")
        headers = {"X-CSRF-Token": csrf}
        catalog_response = await client.get("/api/v1/catalog/releases")
        catalog_response.raise_for_status()
        catalog = catalog_response.json()
        if not catalog["items"]:
            raise RuntimeError("the public catalog has no playable release")
        release_id = catalog["items"][0]["id"]

        playthrough_ids: list[str] = []
        for index in range(args.playthroughs):
            response = await client.post(
                "/api/v1/playthroughs",
                headers=headers,
                json={
                    "release_id": release_id,
                    "name": f"并发玩家{index + 1}",
                    "age": 20,
                    "gender": "female",
                },
            )
            response.raise_for_status()
            playthrough_ids.append(response.json()["id"])

        normal_durations = [
            await _timed_state(client, playthrough_id)
            for playthrough_id in playthrough_ids[: min(20, len(playthrough_ids))]
        ]
        normal_ordered = sorted(normal_durations)
        normal_p95_index = max(0, int(len(normal_ordered) * 0.95) - 1)
        normal_p95 = normal_ordered[normal_p95_index]
        print(
            f"normal state reads: count={len(normal_durations)} "
            f"p50={statistics.median(normal_durations):.1f}ms "
            f"p95={normal_p95:.1f}ms"
        )

        concurrent_durations = await asyncio.gather(
            *(_timed_state(client, playthrough_id) for playthrough_id in playthrough_ids)
        )
        ordered = sorted(concurrent_durations)
        p95_index = max(0, int(len(ordered) * 0.95) - 1)
        concurrent_p95 = ordered[p95_index]
        print(
            f"concurrent state reads: count={len(concurrent_durations)} "
            f"p50={statistics.median(concurrent_durations):.1f}ms "
            f"p95={concurrent_p95:.1f}ms"
        )

        if args.action_check:
            target = playthrough_ids[0]

            async def act(index: int) -> int:
                response = await client.post(
                    f"/api/v1/playthroughs/{target}/actions",
                    headers=headers,
                    json={
                        "text": "观察周围",
                        "idempotency_key": f"load-{uuid.uuid4().hex}-{index}",
                    },
                )
                return response.status_code

            statuses = await asyncio.gather(act(1), act(2))
            if statuses != [200, 200]:
                raise RuntimeError(f"same-world action check failed: {statuses}")
            print("same-world actions: 2/2 completed through the serialized world lock")

        return 0 if normal_p95 <= args.max_p95_ms else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Staging playthrough concurrency smoke")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email")
    parser.add_argument("--password", default="load-smoke-correct-horse")
    parser.add_argument("--playthroughs", type=int, default=50)
    parser.add_argument("--max-p95-ms", type=float, default=300)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--action-check", action="store_true")
    parser.add_argument(
        "--trust-env",
        action="store_true",
        help="honor HTTP(S)_PROXY environment variables",
    )
    args = parser.parse_args()
    if args.playthroughs < 1:
        parser.error("--playthroughs must be positive")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())

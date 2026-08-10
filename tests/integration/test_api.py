"""API surface tests (Prompt sections 50, 52, 53).

Exercised against a real ASGI app backed by a real (in-memory SQLite) database.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(monkeypatch, tmp_path, pack, registry):
    """A fully isolated app: its own database file, its own orchestrator, no LLM.

    Every seam the app uses to reach global state is redirected here, so a test
    run can never touch the developer's ./data/game.db.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import apps.api.deps as deps
    import database.session as db_session
    from database.base import Base
    from engine.core.config import Settings
    from engine.orchestrator.factory import build_orchestrator

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}",
        llm_provider="null",
        debug_mode=True,
        embedding_dim=128,
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # database.session is looked up by module global at call time
    monkeypatch.setattr(db_session, "get_engine", lambda *_a, **_k: engine)
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda *_a, **_k: maker)
    # apps.api.deps imported the name directly, so patch it there as well
    monkeypatch.setattr(deps, "get_sessionmaker", lambda *_a, **_k: maker)
    monkeypatch.setattr(deps, "settings_dep", lambda: settings)

    orchestrator = build_orchestrator(settings=settings, pack=pack, registry=registry)
    monkeypatch.setattr(deps, "orchestrator_dep", lambda: orchestrator)

    from apps.api.main import create_app

    app = create_app()
    # dependency_overrides is the sanctioned seam for the Depends(...) defaults
    app.dependency_overrides[deps.settings_dep] = lambda: settings
    app.dependency_overrides[deps.orchestrator_dep] = lambda: orchestrator
    app.dependency_overrides[deps.pack_dep] = lambda: pack

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as c,
        app.router.lifespan_context(app),
    ):
        yield c
    await engine.dispose()


async def test_health(client) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_start_game_then_act(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-1"}
    )
    assert started.status_code == 200, started.text
    payload = started.json()
    session_id = payload["session_id"]
    assert payload["opening"]
    assert payload["state"]["location"]["name"]

    acted = await client.post(
        f"/api/game/{session_id}/action", json={"text": "我环顾四周", "debug": True}
    )
    assert acted.status_code == 200, acted.text
    turn = acted.json()
    assert turn["narrative"]
    assert turn["turn_id"]
    assert turn["debug"]["intent"]["action_type"] == "OBSERVE"

    state = await client.get(f"/api/game/{session_id}/state")
    assert state.status_code == 200
    assert state.json()["session"]["turn_number"] == 1

    history = await client.get(f"/api/game/{session_id}/history")
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["player_input"] == "我环顾四周"


async def test_action_response_shape_matches_the_contract(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-2"}
    )
    session_id = started.json()["session_id"]
    turn = (
        await client.post(f"/api/game/{session_id}/action", json={"text": "我打坐修炼一个时辰"})
    ).json()
    for key in ("narrative", "state_changes", "visible_updates", "choices"):
        assert key in turn
    assert isinstance(turn["choices"], list)
    assert turn["state_changes"]["world_minute"][1] > turn["state_changes"]["world_minute"][0]


async def test_idempotency_header_is_honoured(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-3"}
    )
    session_id = started.json()["session_id"]
    headers = {"Idempotency-Key": "abc-123"}
    first = await client.post(
        f"/api/game/{session_id}/action", json={"text": "我打坐修炼一个时辰"}, headers=headers
    )
    second = await client.post(
        f"/api/game/{session_id}/action", json={"text": "我打坐修炼一个时辰"}, headers=headers
    )
    assert first.json()["turn_id"] == second.json()["turn_id"]

    state = await client.get(f"/api/game/{session_id}/state")
    assert state.json()["session"]["turn_number"] == 1


async def test_sse_stream_settles_the_world_before_narrating(client) -> None:
    """Prompt section 49: the world is settled before narration starts.

    The prose is now streamed as it is written, so "state first" is no longer
    the observable form of this - the final state carries the chapter's beat
    and cannot exist before the chapter does. What still must hold is that
    every committed step is announced before the first character of prose.
    """
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-4"}
    )
    session_id = started.json()["session_id"]
    async with client.stream(
        "POST", f"/api/game/{session_id}/action/stream", json={"text": "我环顾四周"}
    ) as response:
        assert response.status_code == 200
        body = ""
        async for chunk in response.aiter_text():
            body += chunk

    assert "event: narrative" in body
    if "event: progress" in body:
        assert body.rindex("event: progress") < body.index("event: narrative")
    # State always precedes the terminator, and the terminator is last.
    assert body.index("event: state") < body.index("event: done")
    assert body.rstrip().endswith("}") and "event: done" in body


async def test_inventory_relationships_and_quests(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-5"}
    )
    session_id = started.json()["session_id"]

    inventory = (await client.get(f"/api/game/{session_id}/inventory")).json()
    assert inventory and all("name" in row for row in inventory)

    quests = (await client.get(f"/api/game/{session_id}/quests")).json()
    assert any(q["status"] == "offered" for q in quests)

    relationships = (await client.get(f"/api/game/{session_id}/relationships")).json()
    assert isinstance(relationships, list)


async def test_debug_trace_endpoint(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-6"}
    )
    session_id = started.json()["session_id"]
    turn = (
        await client.post(f"/api/game/{session_id}/action", json={"text": "我环顾四周"})
    ).json()

    trace = await client.get(f"/api/debug/turn/{turn['turn_id']}")
    assert trace.status_code == 200
    body = trace.json()
    assert body["stage_timings"]
    assert "intent" in body and "rule_result" in body
    assert "rng_traces" in body


async def test_world_inspector(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-7"}
    )
    world_id = started.json()["world_id"]

    inspector = await client.get(f"/api/admin/world/{world_id}/inspector")
    assert inspector.status_code == 200
    body = inspector.json()
    assert body["world"]["character_count"] > 10
    assert body["factions"]
    assert body["plot_threads"]
    assert body["director_events"]
    assert {event["status"] for event in body["director_events"]} == {"SCHEDULED"}
    assert "band" in body["tension"]


async def test_inspector_knowledge_view_shows_beliefs_not_truth(client) -> None:
    started = await client.post(
        "/api/game/start", json={"player_name": "沈砚", "world_seed": "api-test-8"}
    )
    world_id = started.json()["world_id"]
    inspector = (await client.get(f"/api/admin/world/{world_id}/inspector")).json()
    npc = next(c for c in inspector["characters"] if c["character_type"] == "MAJOR_NPC")

    knowledge = await client.get(f"/api/admin/character/{npc['id']}/knowledge")
    assert knowledge.status_code == 200
    rows = knowledge.json()
    assert all("state" in r and "confidence" in r for r in rows)
    assert all("truth_value" not in r for r in rows)


async def test_unknown_session_is_a_404(client) -> None:
    response = await client.get("/api/game/does-not-exist/state")
    assert response.status_code == 404


async def test_worlds_and_characters_endpoints(client) -> None:
    created = await client.post("/api/worlds", json={"world_seed": "api-test-9"})
    assert created.status_code == 201, created.text
    world = created.json()
    assert world["character_count"] > 10
    assert world["location_count"] > 5

    fetched = await client.get(f"/api/worlds/{world['id']}")
    assert fetched.status_code == 200

    inspector = (await client.get(f"/api/admin/world/{world['id']}/inspector")).json()
    npc_id = inspector["characters"][0]["id"]

    character = await client.get(f"/api/characters/{npc_id}")
    assert character.status_code == 200
    assert character.json()["realm_display"]

    relationships = await client.get(f"/api/characters/{npc_id}/relationships")
    assert relationships.status_code == 200

    memories = await client.get(f"/api/characters/{npc_id}/memories")
    assert memories.status_code == 200

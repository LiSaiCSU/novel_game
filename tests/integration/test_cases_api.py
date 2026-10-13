"""Deduction case API: ownership, legal moves, and no leaked solution."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def _register(client, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery", "display_name": "侦探"},
    )
    assert response.status_code == 201, response.text
    return client.cookies.get("ng_csrf")


async def _move(client, csrf: str, run_id: str, **body):
    return await client.post(
        f"/api/v1/case-runs/{run_id}/moves", headers={"X-CSRF-Token": csrf}, json=body
    )


async def test_case_run_plays_to_a_verdict(client) -> None:
    catalog = await client.get("/api/v1/cases")
    assert catalog.status_code == 200
    assert any(case["key"] == "egret_purser" for case in catalog.json())

    csrf = await _register(client, "detective@example.com")
    created = await client.post(
        "/api/v1/case-runs", headers={"X-CSRF-Token": csrf}, json={"case_key": "egret_purser"}
    )
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "briefing"
    assert run["case"]["briefing"] and run["case"]["rules"]
    run_id = run["id"]

    response = await _move(client, csrf, run_id, kind="examine", target="body")
    assert response.status_code == 409  # briefing must be finished first

    for body in (
        {"kind": "begin"},
        {"kind": "examine", "target": "cards"},
        {"kind": "talk", "target": "song"},
        {"kind": "present", "target": "sb_cards", "evidence": "score_sheet"},
    ):
        response = await _move(client, csrf, run_id, **body)
        assert response.status_code == 200, response.text
    view = response.json()
    song = next(c for c in view["characters"] if c["key"] == "song")
    assert [s["broken"] for s in song["statements"]] == [True, False]
    assert view["progress"]["lies_broken"] == 1
    assert "contradicted_by" not in response.text and '"lie"' not in response.text

    illegal = await _move(client, csrf, run_id, kind="present", target="sb_deck", evidence="cigar_ash")
    assert illegal.status_code == 409

    verdict = await _move(
        client, csrf, run_id, kind="accuse", culprit="song", weapon="cane", motive="fraud",
        exhibits=["score_sheet"],
    )
    assert verdict.status_code == 200, verdict.text
    assert verdict.json()["status"] == "closed"
    assert verdict.json()["result"]["ending"] == "escaped"

    mine = await client.get("/api/v1/case-runs")
    assert mine.json()[0]["ending_title"] == verdict.json()["result"]["title"]


async def test_case_runs_are_private(client) -> None:
    csrf = await _register(client, "first@example.com")
    created = await client.post(
        "/api/v1/case-runs", headers={"X-CSRF-Token": csrf}, json={"case_key": "egret_purser"}
    )
    run_id = created.json()["id"]
    await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    client.cookies.clear()
    other_csrf = await _register(client, "second@example.com")
    assert (await client.get(f"/api/v1/case-runs/{run_id}")).status_code == 404
    assert (await _move(client, other_csrf, run_id, kind="begin")).status_code == 404


async def test_free_text_needs_a_configured_model(client) -> None:
    csrf = await _register(client, "talker@example.com")
    run_id = (
        await client.post(
            "/api/v1/case-runs", headers={"X-CSRF-Token": csrf}, json={"case_key": "egret_purser"}
        )
    ).json()["id"]
    await _move(client, csrf, run_id, kind="begin")
    await _move(client, csrf, run_id, kind="talk", target="xiaoshun")
    response = await client.post(
        f"/api/v1/case-runs/{run_id}/say",
        headers={"X-CSRF-Token": csrf},
        json={"character": "xiaoshun", "text": "你别怕，慢慢说"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "case_model_unavailable"
    # A refused free question costs no time.
    view = (await client.get(f"/api/v1/case-runs/{run_id}")).json()
    assert view["minutes_left"] == view["case"]["minutes_total"]

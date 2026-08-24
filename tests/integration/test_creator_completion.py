"""The guided authoring surfaces a writer actually touches.

Two very different failures used to look identical in the browser: an autosave
rejected because a required field was momentarily blank, and a model outage.
Both arrived as an English blob that the client could only render as
"请求没有完成，请稍后重试。", so the writer had nothing to act on. These tests
pin the structured shape that replaced it.
"""

from __future__ import annotations

import pytest

from apps.api.creator_ai import (
    CompletionCharacter,
    CompletionEnding,
    CompletionFact,
    CompletionQuest,
    CreatorUsageSettlement,
    StoryCompletion,
    apply_completion,
    document_gaps,
)
from apps.authoring.templates import build_project_template
from engine.contentpack.compiler import compile_package, validate_package_graph


async def _author(client, email: str) -> str:
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-author", "display_name": "作者"},
    )
    assert registered.status_code == 201, registered.text
    return client.cookies.get("ng_csrf")


async def _project(client, csrf: str) -> tuple[str, dict, int]:
    created = await client.post(
        "/api/v1/creator/projects",
        headers={"X-CSRF-Token": csrf},
        json={"title": "新故事", "summary": "一句话简介。", "template_key": "mystery"},
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    loaded = (await client.get(f"/api/v1/creator/projects/{project_id}")).json()
    return project_id, loaded["document"], loaded["revision"]


async def test_blank_required_field_names_the_field_instead_of_failing_opaquely(client) -> None:
    csrf = await _author(client, "blank-title@example.com")
    project_id, document, revision = await _project(client, csrf)

    # Clearing the placeholder title before typing a real one is the most
    # common first action in the editor, and autosave fires while it is empty.
    document["manifest"]["title"] = ""
    response = await client.put(
        f"/api/v1/creator/projects/{project_id}/document",
        headers={"X-CSRF-Token": csrf},
        json={"expected_revision": revision, "document": document},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "document_invalid"
    assert {item["field"] for item in detail["problems"]} == {"manifest.title"}
    assert detail["problems"][0]["message"]


async def test_immutable_slug_rejection_carries_a_code(client) -> None:
    csrf = await _author(client, "codes@example.com")
    project_id, document, revision = await _project(client, csrf)

    document["manifest"]["slug"] = "a-different-slug"
    renamed = await client.put(
        f"/api/v1/creator/projects/{project_id}/document",
        headers={"X-CSRF-Token": csrf},
        json={"expected_revision": revision, "document": document},
    )

    assert renamed.status_code == 422
    assert renamed.json()["detail"]["code"] == "document_slug_immutable"


def test_completion_only_fills_blanks_and_stays_compilable() -> None:
    package = build_project_template(
        "mystery", title="雾中来信", slug="fill-blanks", summary="简介", locale="zh-CN", rating="all"
    )
    author_goal = package.content.characters[0]["long_term_goal"]
    assert document_gaps(package)["endings"]

    merged, added = apply_completion(
        package,
        StoryCompletion(
            endings=[
                CompletionEnding(title="真相大白", kind="success", epilogue="登记本终于对上了。" * 4),
                CompletionEnding(title="代价", kind="cost", epilogue="你保住展品，丢了证人。" * 4),
                CompletionEnding(title="不了了之", kind="quiet", epilogue="没有人再提那份清单。" * 4),
            ],
            facts=[
                CompletionFact(
                    statement="闭馆记录被人重抄过一遍", sensitivity=0.7, known_by="沉稳的合作者"
                )
            ],
            quests=[CompletionQuest(name="核对闭馆时间", goal_summary="比对三人记得的时间")],
            characters=[
                CompletionCharacter(
                    character_key="steady_partner",
                    long_term_goal="不该被写进来的目标",
                    short_term_goal="拿到登记本",
                    secret="他自己改过时间",
                )
            ],
        ),
    )

    assert added["endings"] == 3
    assert validate_package_graph(merged) == []
    assert compile_package(merged).checksum
    # The author already wrote this character's long-term goal, so completion
    # must leave it alone. Overwriting it would silently destroy their work.
    assert merged.content.characters[0]["long_term_goal"] == author_goal
    # Naming a character turns the new fact into a real information asymmetry,
    # which is the only reason a secret is worth having in this engine.
    assert merged.content.facts[-1]["initial_knowledge"] == {
        "steady_partner": {"state": "KNOWN", "confidence": 1, "source": "SEED"}
    }
    assert "endings" not in document_gaps(merged)


@pytest.mark.parametrize("known_by", ["沉稳的合作者", "steady_partner"])
def test_completion_accepts_a_character_key_or_display_name(known_by: str) -> None:
    package = build_project_template(
        "mystery", title="T", slug="who-knows", summary="简介", locale="zh-CN", rating="all"
    )
    merged, _added = apply_completion(
        package,
        StoryCompletion(
            facts=[CompletionFact(statement="登记本被重抄过", sensitivity=0.5, known_by=known_by)]
        ),
    )
    assert merged.content.facts[-1]["subject"] == "steady_partner"


async def test_ai_complete_returns_a_reviewable_draft_without_saving(client, monkeypatch) -> None:
    from apps.api.routers import creator as creator_router

    async def fake_runtime(**_kwargs):
        return object()

    async def fake_complete(_runtime, *, package, gaps):
        assert "endings" in gaps
        assert package.manifest.title == "新故事"
        return StoryCompletion(
            endings=[
                CompletionEnding(title="真相大白", kind="success", epilogue="登记本对上了。" * 5),
                CompletionEnding(title="不了了之", kind="quiet", epilogue="没有人再提起。" * 5),
            ],
            quests=[CompletionQuest(name="核对闭馆时间", goal_summary="比对三人的说法")],
        )

    async def fake_usage(*_args, **_kwargs):
        return CreatorUsageSettlement(billable_cost_microunits=0, records=0)

    monkeypatch.setattr(creator_router, "creator_ai_runtime", fake_runtime)
    monkeypatch.setattr(creator_router, "complete_story", fake_complete)
    monkeypatch.setattr(creator_router, "record_creator_usage", fake_usage)

    csrf = await _author(client, "completion@example.com")
    project_id, _document, revision = await _project(client, csrf)

    response = await client.post(
        f"/api/v1/creator/projects/{project_id}/ai-complete",
        headers={"X-CSRF-Token": csrf},
        json={"idempotency_key": "creator-complete-0001", "model_mode": "platform"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["added"]["endings"] == 2
    assert payload["diagnostics"] == []
    assert [item["title"] for item in payload["document"]["content"]["endings"]] == [
        "真相大白",
        "不了了之",
    ]
    # Returning a draft must not touch the stored revision: the editor applies
    # it through the normal save path, which keeps undo and conflict handling.
    after = (await client.get(f"/api/v1/creator/projects/{project_id}")).json()
    assert after["revision"] == revision
    assert after["document"]["content"]["endings"] == []


async def test_ai_complete_refuses_when_there_is_nothing_left_to_fill(client, monkeypatch) -> None:
    from apps.api.routers import creator as creator_router

    monkeypatch.setattr(creator_router, "document_gaps", lambda _package: {})

    csrf = await _author(client, "nothing-to-do@example.com")
    project_id, _document, _revision = await _project(client, csrf)

    response = await client.post(
        f"/api/v1/creator/projects/{project_id}/ai-complete",
        headers={"X-CSRF-Token": csrf},
        json={"idempotency_key": "creator-complete-0002", "model_mode": "platform"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "creator_nothing_to_complete"


async def test_ai_complete_reports_a_model_outage_with_an_actionable_code(
    client, monkeypatch
) -> None:
    from apps.api.routers import creator as creator_router

    async def unavailable(**_kwargs):
        raise ValueError("platform inference quota exhausted")

    monkeypatch.setattr(creator_router, "creator_ai_runtime", unavailable)

    csrf = await _author(client, "outage@example.com")
    project_id, _document, _revision = await _project(client, csrf)

    response = await client.post(
        f"/api/v1/creator/projects/{project_id}/ai-complete",
        headers={"X-CSRF-Token": csrf},
        json={"idempotency_key": "creator-complete-0003", "model_mode": "platform"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "creator_model_unavailable"

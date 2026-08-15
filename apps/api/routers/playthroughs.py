"""Authenticated, user-owned playthrough lifecycle API."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from apps.api.deps import settings_dep, uow_dep
from apps.api.product_analytics import record_product_event
from apps.api.runtime import (
    InferenceQuotaExceeded,
    RuntimeConfigurationError,
    release_content_cache,
    release_runtime_service,
)
from apps.api.security import Principal, require_csrf, token_hash, verified_principal
from apps.api.tenancy import set_tenant_context
from database.models.orm import SaveSlotORM
from database.models.platform import ContentReleaseORM, PlaythroughORM
from database.repositories.sql import SqlUnitOfWork
from database.saves import SaveService
from database.seeding import persist_bundle
from engine.contentpack.schema_v2 import ContentPackageV2, EndingDefinition, PlayerField
from engine.core.config import Settings
from engine.core.ids import PLAYER_KEY, new_id
from engine.core.models import Event, NarrativeSegment
from engine.core.mutations import ChangeSet, character_field
from engine.core.types import Visibility
from engine.endings import build_ending_context, evaluate_endings
from engine.orchestrator.turn import DEFAULT_NARRATIVE_CHARS
from engine.world.seeder import PlayerSpec, build_world
from engine.world.state_view import build_world_state

router = APIRouter(tags=["v1-catalog", "v1-playthroughs"])

NARRATIVE_LENGTH_PRESETS: dict[str, dict[str, int | str]] = {
    "concise": {"label": "精简", "min_chars": 680, "max_chars": 800},
    "standard": {"label": "标准", "min_chars": 1360, "max_chars": 1600},
    "detailed": {"label": "丰富", "min_chars": 2040, "max_chars": 2400},
    "long": {"label": "长篇", "min_chars": 3060, "max_chars": 3600},
}
DEFAULT_NARRATIVE_LENGTH = "standard"


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _runtime_for(
    release: ContentReleaseORM,
    play: PlaythroughORM,
    principal: Principal,
    uow: SqlUnitOfWork,
    settings: Settings,
):
    try:
        return await release_runtime_service.resolve(
            release, play, principal.user_id, uow, settings
        )
    except InferenceQuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RuntimeConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class PlaythroughCreate(BaseModel):
    release_id: str
    scenario_key: str | None = None
    name: str = Field(min_length=1, max_length=80)
    age: int = Field(default=18, ge=18, le=80)
    background: str = Field(default="", max_length=2000)
    gender: str = "female"
    player_config: dict[str, Any] = Field(default_factory=dict)
    preview: bool = False
    share_token: str | None = None


class PlayAction(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    idempotency_key: str | None = None
    narrative_max_chars: int | None = Field(default=None, ge=400, le=4000)


class PlaythroughSettingsWrite(BaseModel):
    narrative_length: Literal["concise", "standard", "detailed", "long"]


class RomanceConsentWrite(BaseModel):
    decision: Literal["accepted", "rejected", "undecided"]


class EndingChoice(BaseModel):
    ending_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")


class SaveCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _field_value(field: PlayerField, supplied: dict[str, Any]) -> Any:
    value = supplied.get(field.key, field.default)
    if field.required and (value is None or value == "" or value == []):
        raise HTTPException(status_code=422, detail=f"player field {field.key!r} is required")
    if value is None:
        return None
    if field.type == "integer":
        if isinstance(value, bool):
            raise HTTPException(
                status_code=422, detail=f"player field {field.key!r} must be an integer"
            )
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail=f"player field {field.key!r} must be an integer"
            ) from exc
        if field.minimum is not None and value < field.minimum:
            raise HTTPException(
                status_code=422, detail=f"player field {field.key!r} is below its minimum"
            )
        if field.maximum is not None and value > field.maximum:
            raise HTTPException(
                status_code=422, detail=f"player field {field.key!r} exceeds its maximum"
            )
    elif field.type == "tags":
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        if (
            not isinstance(value, list)
            or len(value) > 12
            or any(not isinstance(item, str) for item in value)
        ):
            raise HTTPException(
                status_code=422, detail=f"player field {field.key!r} must be a list of tags"
            )
    elif field.type in {"text", "choice"} and not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"player field {field.key!r} must be text")
    if field.type == "choice":
        allowed = {item.get("value") for item in field.choices}
        if value not in allowed:
            raise HTTPException(
                status_code=422, detail=f"player field {field.key!r} is not an allowed choice"
            )
    return value


def _player_spec(release: ContentReleaseORM, body: PlaythroughCreate) -> PlayerSpec:
    package = ContentPackageV2.model_validate(
        {"manifest": release.artifact["manifest"], "content": release.artifact["content"]}
    )
    supplied = {
        "name": body.name,
        "age": body.age,
        "background": body.background,
        **body.player_config,
    }
    allowed = {field.key for field in package.manifest.player_fields}
    unknown = (
        set(body.player_config)
        - allowed
        - {
            "model_mode",
            "provider",
            "narrative_length",
            "narrative_max_chars",
        }
    )
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"unknown player fields: {', '.join(sorted(unknown))}"
        )
    values = {field.key: _field_value(field, supplied) for field in package.manifest.player_fields}
    scenario_key = body.scenario_key or package.manifest.entry_scenario
    scenario = next(item for item in package.content.scenarios if item.key == scenario_key)
    template = scenario.player_template
    constraints = dict(template.get("constraints", {}) or {})
    required_gender = constraints.get("gender")
    if required_gender and body.gender != required_gender:
        raise HTTPException(
            status_code=422, detail="player gender is incompatible with this scenario"
        )
    minimum_age = int(constraints.get("minimum_age", 18))
    maximum_age = int(constraints.get("maximum_age", 80))
    if not minimum_age <= body.age <= maximum_age:
        raise HTTPException(status_code=422, detail="player age is incompatible with this scenario")
    bound: dict[str, dict[str, Any]] = {
        "attribute": dict(template.get("attributes", {}) or {}),
        "resource": dict(template.get("resources", {}) or {}),
        "progression": dict(template.get("progressions", {}) or {}),
        "property": dict(template.get("properties", {}) or {}),
    }
    for field in package.manifest.player_fields:
        if field.key not in {"name", "age", "background"} and values.get(field.key) is not None:
            bound[field.binding][field.key] = values[field.key]
    return PlayerSpec(
        name=str(values.get("name") or body.name),
        gender=body.gender,
        age=int(values.get("age") or body.age),
        background=str(values.get("background") or body.background),
        attributes=bound["attribute"],
        resources=bound["resource"],
        progressions=bound["progression"],
        properties=bound["property"],
    )


async def _owned_playthrough(
    uow: SqlUnitOfWork, playthrough_id: str, user_id: str
) -> PlaythroughORM:
    row = await uow.session.scalar(
        sa.select(PlaythroughORM).where(
            PlaythroughORM.id == playthrough_id,
            PlaythroughORM.user_id == user_id,
            PlaythroughORM.status != "deleted",
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="playthrough not found")
    return row


def _playthrough_settings(play: PlaythroughORM) -> dict[str, Any]:
    config = dict(play.player_config or {})
    key = str(config.get("narrative_length") or DEFAULT_NARRATIVE_LENGTH)
    if key not in NARRATIVE_LENGTH_PRESETS:
        key = DEFAULT_NARRATIVE_LENGTH
    selected = NARRATIVE_LENGTH_PRESETS[key]
    return {
        "narrative_length": key,
        "narrative_max_chars": int(config.get("narrative_max_chars") or selected["max_chars"]),
        "presets": [
            {"key": preset_key, **preset} for preset_key, preset in NARRATIVE_LENGTH_PRESETS.items()
        ],
    }


def narrative_max_chars(play: PlaythroughORM, requested: int | None = None) -> int:
    if requested is not None:
        return requested
    return int(_playthrough_settings(play).get("narrative_max_chars", DEFAULT_NARRATIVE_CHARS))


def _release_package(release: ContentReleaseORM) -> ContentPackageV2:
    return ContentPackageV2.model_validate(
        {"manifest": release.artifact["manifest"], "content": release.artifact["content"]}
    )


async def _ending_snapshot(
    uow: SqlUnitOfWork,
    play: PlaythroughORM,
    release: ContentReleaseORM,
    settings: Settings,
):
    session = await uow.sessions.get(play.game_session_id or "")
    if session is None:
        raise HTTPException(status_code=409, detail="playthrough runtime is incomplete")
    package = _release_package(release)
    pack = release_content_cache.resolve(release, settings)
    state = await build_world_state(uow, pack, session.world_id, session.player_character_id)
    context = await build_ending_context(uow, state, package.content.endings)
    evaluations = evaluate_endings(package.content.endings, context)
    return package, session, state, context, evaluations


@router.post("/playthroughs", status_code=201)
async def create_playthrough(
    body: PlaythroughCreate,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    release = await uow.session.get(ContentReleaseORM, body.release_id)
    if release is None or release.moderation_status not in {"approved"}:
        raise HTTPException(status_code=404, detail="release not found")
    if body.preview and release.owner_id != principal.user_id:
        raise HTTPException(status_code=404, detail="release not found")
    if not body.preview and release.visibility not in {"public", "unlisted"}:
        raise HTTPException(status_code=404, detail="release not found")
    if release.visibility == "unlisted" and release.owner_id != principal.user_id:
        supplied = token_hash(body.share_token or "", settings.auth_pepper)
        if not release.share_token_hash or supplied != release.share_token_hash:
            raise HTTPException(status_code=404, detail="release not found")
    scenario = body.scenario_key or release.artifact["manifest"]["entry_scenario"]
    allowed = {item["key"] for item in release.artifact["content"]["scenarios"]}
    if scenario not in allowed:
        raise HTTPException(status_code=422, detail="scenario does not exist")
    pack = release_content_cache.resolve(release, settings)
    bundle = build_world(
        pack,
        world_seed=f"play-{new_id()}",
        player=_player_spec(release, body),
        session_seed=f"session-{new_id()}",
    )
    assert bundle.session is not None
    player_config = dict(body.player_config)
    requested_length = str(player_config.get("narrative_length") or DEFAULT_NARRATIVE_LENGTH)
    if requested_length not in NARRATIVE_LENGTH_PRESETS:
        raise HTTPException(status_code=422, detail="unknown narrative length preset")
    player_config["narrative_length"] = requested_length
    player_config["narrative_max_chars"] = NARRATIVE_LENGTH_PRESETS[requested_length]["max_chars"]
    playthrough = PlaythroughORM(
        id=new_id(),
        user_id=principal.user_id,
        release_id=release.id,
        scenario_key=scenario,
        world_id=bundle.world.id,
        game_session_id=bundle.session.id,
        name=body.name,
        is_preview=body.preview,
        expires_at=datetime.now(UTC) + timedelta(hours=24) if body.preview else None,
        player_config=player_config,
    )
    bundle.world.release_id = release.id
    bundle.world.playthrough_id = playthrough.id
    bundle.session.playthrough_id = playthrough.id
    runtime = await _runtime_for(release, playthrough, principal, uow, settings)
    uow.session.add(playthrough)
    # RLS on worlds checks the owning playthrough. Flush the owner row first so
    # the policy can see it in this same transaction.
    await uow.session.flush()
    await persist_bundle(uow.session, bundle)
    await uow.commit()
    player = bundle.character_by_key(PLAYER_KEY)
    assert player is not None
    state = await build_world_state(uow, runtime.pack, bundle.world.id, player.id)
    prologue = await runtime.orchestrator.open_session(uow, bundle.session, state)
    await release_runtime_service.record_usage(runtime, principal.user_id, playthrough.id, uow)
    await record_product_event(
        uow,
        principal,
        "preview_started" if body.preview else "playthrough_started",
        playthrough_id=playthrough.id,
        release_id=release.id,
        dedupe_key=playthrough.id,
        properties={
            "scenario_key": scenario,
            **({"model_mode": runtime.credential_mode} if not body.preview else {}),
        },
    )
    await uow.commit()
    return {
        "id": playthrough.id,
        "release_id": release.id,
        "session_id": bundle.session.id,
        "opening": prologue.text,
        "state": state.scene_summary(),
    }


@router.get("/playthroughs")
async def list_playthroughs(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> list[dict[str, Any]]:
    await set_tenant_context(uow.session, principal.user_id)
    rows = (
        await uow.session.execute(
            sa.select(PlaythroughORM, ContentReleaseORM)
            .join(ContentReleaseORM, ContentReleaseORM.id == PlaythroughORM.release_id)
            .where(
                PlaythroughORM.user_id == principal.user_id,
                PlaythroughORM.status != "deleted",
            )
            .order_by(PlaythroughORM.updated_at.desc())
        )
    ).all()
    return [
        {
            "id": play.id,
            "name": play.name,
            "status": play.status,
            "preview": play.is_preview,
            "ending": {"key": play.ending_key, "title": play.ending_title}
            if play.ending_key
            else None,
            "release": {"id": release.id, "title": release.title},
            "settings": _playthrough_settings(play),
            "updated_at": play.updated_at,
        }
        for play, release in rows
    ]


@router.get("/playthroughs/{playthrough_id}/settings")
async def get_playthrough_settings(
    playthrough_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    return _playthrough_settings(play)


@router.put("/playthroughs/{playthrough_id}/settings")
async def update_playthrough_settings(
    playthrough_id: str,
    body: PlaythroughSettingsWrite,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    selected = NARRATIVE_LENGTH_PRESETS[body.narrative_length]
    play.player_config = {
        **dict(play.player_config or {}),
        "narrative_length": body.narrative_length,
        "narrative_max_chars": selected["max_chars"],
    }
    play.updated_at = datetime.now(UTC)
    await uow.commit()
    return _playthrough_settings(play)


@router.delete("/playthroughs/{playthrough_id}", status_code=204)
async def delete_playthrough(
    playthrough_id: str,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> Response:
    """Remove a story from the player's library without destroying audit data."""
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    play.status = "deleted"
    play.player_config = {
        **dict(play.player_config or {}),
        "deleted_at": datetime.now(UTC).isoformat(),
    }
    play.updated_at = datetime.now(UTC)
    await uow.commit()
    return Response(status_code=204)


@router.get("/playthroughs/{playthrough_id}/state")
async def playthrough_state(
    playthrough_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    release = await uow.session.get(ContentReleaseORM, play.release_id)
    session = await uow.sessions.get(play.game_session_id or "")
    if release is None or session is None:
        raise HTTPException(status_code=409, detail="playthrough runtime is incomplete")
    pack = release_content_cache.resolve(release, settings)
    state = await build_world_state(uow, pack, session.world_id, session.player_character_id)
    return {
        **state.scene_summary(),
        "playthrough": {
            "status": play.status,
            "ending_key": play.ending_key,
            "ending_title": play.ending_title,
            "completed_at": play.completed_at,
            "settings": _playthrough_settings(play),
        },
    }


@router.get("/playthroughs/{playthrough_id}/endings")
async def playthrough_endings(
    playthrough_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    release = await uow.session.get(ContentReleaseORM, play.release_id)
    if release is None:
        raise HTTPException(status_code=409, detail="playthrough runtime is incomplete")
    package, _session, _state, context, evaluations = await _ending_snapshot(
        uow, play, release, settings
    )
    inspector = play.is_preview or principal.has_role("admin")
    visible: list[dict[str, Any]] = []
    hidden_count = 0
    for row in evaluations:
        if row.hidden_until_available and not row.available and not inspector:
            hidden_count += 1
            continue
        item = row.model_dump(mode="json")
        if not row.available and not inspector:
            item["epilogue"] = ""
        visible.append(item)
    lead_names = {
        str(character.get("key")): str(character.get("name") or character.get("key"))
        for character in package.content.characters
        if any(ending.lead == character.get("key") for ending in package.content.endings)
    }
    return {
        "status": play.status,
        "selected": {
            "key": play.ending_key,
            "title": play.ending_title,
            "completed_at": play.completed_at,
        }
        if play.ending_key
        else None,
        "endings": visible,
        "hidden_count": hidden_count,
        "consent": context["consent"],
        "leads": lead_names,
    }


@router.get("/playthroughs/{playthrough_id}/dashboard")
async def playthrough_dashboard(
    playthrough_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    """Player-visible structured state; no secrets, traces or objective truth."""
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    release = await uow.session.get(ContentReleaseORM, play.release_id)
    session = await uow.sessions.get(play.game_session_id or "")
    if release is None or session is None:
        raise HTTPException(status_code=409, detail="playthrough runtime is incomplete")
    pack = release_content_cache.resolve(release, settings)
    state = await build_world_state(uow, pack, session.world_id, session.player_character_id)
    characters = await uow.characters.list_for_world(state.world.id)
    relationships: list[dict[str, Any]] = []
    for character in characters:
        if character.id == state.player.id:
            continue
        relation = await uow.relationships.get(character.id, state.player.id)
        direction = "toward_player"
        if relation is None:
            relation = await uow.relationships.get(state.player.id, character.id)
            direction = "from_player"
        if relation is None or relation.is_stranger():
            continue
        relationships.append(
            {
                "key": character.key,
                "name": character.display_name,
                "direction": direction,
                "dimensions": relation.as_dict(),
                "tags": relation.tags,
            }
        )
    return {
        "player": {
            "attributes": state.player.attributes,
            "resources": state.player.resources,
            "progressions": state.player.progressions,
            "properties": state.player.properties,
        },
        "inventory": [
            {
                "key": item.item_key,
                "name": state.item_name(item.item_key),
                "quantity": item.quantity,
            }
            for item in state.inventory
        ],
        "abilities": [
            {
                "key": ability.skill_key,
                "name": str((pack.skill(ability.skill_key) or {}).get("name") or ability.skill_key),
                "mastery": ability.mastery,
            }
            for ability in state.known_skills
        ],
        "relationships": relationships,
        "quests": [
            {
                "key": quest.key,
                "name": quest.name,
                "status": str(quest.status),
                "plot_thread": quest.plot_thread_key,
                "expires_at_minute": quest.expires_at_minute,
            }
            for quest in state.active_quests
        ],
        "threads": [
            {
                "key": thread.key,
                "name": thread.name,
                "status": str(thread.status),
                "stage": thread.stage,
                "next_beat_hint": thread.next_beat_hint,
            }
            for thread in state.plot_threads
        ],
        "labels": {
            "relationships": pack.vocabulary.get("relationship_labels", {}),
            "relationship_tags": pack.vocabulary.get("relationship_tag_labels", {}),
            "statuses": pack.vocabulary.get("status_labels", {}),
            "attributes": {
                str(item.get("key")): str(item.get("label") or item.get("key"))
                for item in pack.meta.get("attribute_definitions", [])
            },
            "resources": {
                str(item.get("key")): str(item.get("label") or item.get("key"))
                for item in pack.meta.get("resource_definitions", [])
            },
            "progressions": {
                str(item.get("key")): str(item.get("label") or item.get("key"))
                for item in pack.meta.get("progression_definitions", [])
            },
            "progression_values": {
                **{
                    str(tier.get("key")): str(tier.get("label") or tier.get("key"))
                    for item in pack.meta.get("progression_definitions", [])
                    for tier in item.get("tiers", [])
                },
                **{realm.key: realm.name for realm in pack.realms.realms},
                **{stage.key: stage.name for realm in pack.realms.realms for stage in realm.stages},
            },
        },
    }


def _recap_excerpt(text: str, limit: int = 260) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"…{normalized[-limit:]}"


@router.get("/playthroughs/{playthrough_id}/recap")
async def playthrough_recap(
    playthrough_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    """Deterministic return recap made only from player-visible state and prose."""
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    release = await uow.session.get(ContentReleaseORM, play.release_id)
    session = await uow.sessions.get(play.game_session_id or "")
    if release is None or session is None:
        raise HTTPException(status_code=409, detail="playthrough runtime is incomplete")
    pack = release_content_cache.resolve(release, settings)
    state = await build_world_state(uow, pack, session.world_id, session.player_character_id)
    turns = await uow.turns.list_for_session(session.id, limit=8)
    segments = [
        segment
        for segment in await uow.turns.list_narrative(session.id, limit=8)
        if segment.kind in {"chapter", "scene", "ending"} and segment.text.strip()
    ]
    last_result = dict(turns[-1].get("result") or {}) if turns else {}
    choices = [
        {"label": str(item.get("label", "")), "hint": str(item.get("hint", ""))}
        for item in last_result.get("choices", [])
        if isinstance(item, dict) and item.get("label")
    ][:4]
    return {
        "title": release.title,
        "turn_number": session.turn_number,
        "updated_at": play.updated_at,
        "scene": {
            "time": state.time.label,
            "location": state.location.name if state.location else "",
        },
        "last_action": str(turns[-1].get("player_input") or "") if turns else "",
        "recent": [
            {
                "text": _recap_excerpt(segment.text),
                "world_minute": segment.world_minute,
            }
            for segment in segments[-3:]
        ],
        "objectives": [
            {"type": "quest", "key": quest.key, "name": quest.name, "hint": ""}
            for quest in state.active_quests[:4]
        ]
        + [
            {
                "type": "thread",
                "key": thread.key,
                "name": thread.name,
                "hint": thread.next_beat_hint,
            }
            for thread in state.plot_threads
            if str(thread.status) == "active"
        ][:4],
        "suggestions": choices,
    }


@router.put("/playthroughs/{playthrough_id}/relationships/{lead_key}/consent")
async def set_romance_consent(
    playthrough_id: str,
    lead_key: str,
    body: RomanceConsentWrite,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, str]:
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    if play.status != "active":
        raise HTTPException(status_code=409, detail="completed playthrough cannot change consent")
    release = await uow.session.get(ContentReleaseORM, play.release_id)
    if release is None:
        raise HTTPException(status_code=409, detail="playthrough runtime is incomplete")
    package, _session, state, _context, _evaluations = await _ending_snapshot(
        uow, play, release, settings
    )
    declared_leads = {ending.lead for ending in package.content.endings if ending.lead}
    if lead_key not in declared_leads:
        raise HTTPException(status_code=404, detail="relationship lead not found")
    lead = await uow.characters.get_by_key(state.world.id, lead_key)
    if lead is None or lead.age < 18 or state.player.age < 18:
        raise HTTPException(status_code=409, detail="romance consent requires adult characters")

    before = deepcopy(state.player.properties)
    after = deepcopy(before)
    choices = dict(after.get("romance_consent", {}) or {})
    previous = str(choices.get(lead_key, "undecided"))
    if body.decision == "undecided":
        choices.pop(lead_key, None)
    else:
        choices[lead_key] = body.decision
    after["romance_consent"] = choices
    changes = ChangeSet()
    changes.add(
        character_field(
            state.player.id,
            "properties",
            before,
            after,
            reason=f"player explicitly set romance consent for {lead_key}",
        )
    )
    changes.add_event(
        Event(
            world_id=state.world.id,
            event_type="ROMANCE_CONSENT_CHANGED",
            actor_id=state.player.id,
            target_ids=[lead.id],
            before={"decision": previous},
            after={"decision": body.decision},
            payload={"lead_key": lead_key},
            world_minute=state.world.current_minute,
            importance=0.8,
            visibility=Visibility.LOCAL,
            witnesses=[state.player.id, lead.id],
        )
    )
    await uow.apply(changes)
    await uow.commit()
    return {"lead": lead_key, "decision": body.decision}


@router.post("/playthroughs/{playthrough_id}/ending")
async def choose_playthrough_ending(
    playthrough_id: str,
    body: EndingChoice,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    play = await uow.session.scalar(
        sa.select(PlaythroughORM)
        .where(
            PlaythroughORM.id == playthrough_id,
            PlaythroughORM.user_id == principal.user_id,
        )
        .with_for_update()
    )
    if play is None:
        raise HTTPException(status_code=404, detail="playthrough not found")
    if play.status == "completed":
        if play.ending_key == body.ending_key:
            return {
                "status": play.status,
                "ending_key": play.ending_key,
                "title": play.ending_title,
            }
        raise HTTPException(status_code=409, detail="playthrough already has a different ending")
    if play.status != "active":
        raise HTTPException(status_code=409, detail="playthrough is not active")
    release = await uow.session.get(ContentReleaseORM, play.release_id)
    if release is None:
        raise HTTPException(status_code=409, detail="playthrough runtime is incomplete")
    package, session, state, context, evaluations = await _ending_snapshot(
        uow, play, release, settings
    )
    selected = next((row for row in evaluations if row.key == body.ending_key), None)
    definition: EndingDefinition | None = next(
        (row for row in package.content.endings if row.key == body.ending_key), None
    )
    if selected is None or definition is None:
        raise HTTPException(status_code=404, detail="ending not found")
    if not selected.available:
        raise HTTPException(status_code=409, detail="ending conditions are not satisfied")
    if selected.requires_consent and context["consent"].get(selected.lead) != "accepted":
        raise HTTPException(status_code=409, detail="romance ending requires explicit consent")

    lead = await uow.characters.get_by_key(state.world.id, selected.lead) if selected.lead else None
    changes = ChangeSet()
    changes.add_event(
        Event(
            world_id=state.world.id,
            event_type="PLAYTHROUGH_ENDING_SELECTED",
            actor_id=state.player.id,
            target_ids=[lead.id] if lead else [],
            payload={
                "ending_key": selected.key,
                "ending_type": selected.type,
                "lead_key": selected.lead,
                "release_id": release.id,
            },
            world_minute=state.world.current_minute,
            importance=1.0,
            visibility=Visibility.PUBLIC,
            witnesses=[character.id for character in state.present_characters] + [state.player.id],
        )
    )
    await uow.apply(changes)
    await uow.turns.append_narrative(
        NarrativeSegment(
            session_id=session.id,
            kind="ending",
            text=definition.epilogue,
            world_minute=state.world.current_minute,
        )
    )
    session.status = "completed"
    await uow.sessions.save(session)
    play.status = "completed"
    play.ending_key = selected.key
    play.ending_title = selected.title
    play.completed_at = datetime.now(UTC)
    await record_product_event(
        uow,
        principal,
        "ending_selected",
        playthrough_id=play.id,
        release_id=release.id,
        dedupe_key=play.id,
        properties={"ending_key": selected.key, "ending_type": selected.type},
    )
    await uow.commit()
    return {
        "status": play.status,
        "ending_key": selected.key,
        "title": selected.title,
        "type": selected.type,
        "lead": selected.lead,
        "epilogue": definition.epilogue,
        "completed_at": play.completed_at,
    }


@router.get("/playthroughs/{playthrough_id}/history")
async def playthrough_history(
    playthrough_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, Any]:
    """Return player-visible prose only; traces and hidden canonical state stay private."""
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    session = await uow.sessions.get(play.game_session_id or "")
    if session is None:
        raise HTTPException(status_code=409, detail="playthrough runtime is incomplete")
    turns = await uow.turns.list_for_session(session.id, limit=100)
    by_id = {str(turn["id"]): turn for turn in turns}
    chapters = []
    for segment in await uow.turns.list_narrative(session.id, limit=100):
        if segment.kind not in {"chapter", "scene", "ending"}:
            continue
        turn = by_id.get(str(segment.turn_id or ""), {})
        chapters.append(
            {
                "turn_id": segment.turn_id,
                "input": str(turn.get("player_input") or ""),
                "text": segment.text,
                "world_minute": segment.world_minute,
            }
        )
    last_result = dict(turns[-1].get("result") or {}) if turns else {}
    return {"chapters": chapters, "choices": last_result.get("choices", [])}


@router.post("/playthroughs/{playthrough_id}/saves", status_code=201)
async def create_playthrough_save(
    playthrough_id: str,
    body: SaveCreate,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    if play.status != "active":
        raise HTTPException(status_code=409, detail="completed playthrough cannot be saved")
    session = await uow.sessions.get(play.game_session_id or "")
    release = await uow.session.get(ContentReleaseORM, play.release_id)
    if session is None or release is None:
        raise HTTPException(status_code=409, detail="playthrough runtime is incomplete")
    pack = release_content_cache.resolve(release, settings)
    state = await build_world_state(uow, pack, session.world_id, session.player_character_id)
    segments = await uow.turns.list_narrative(session.id, limit=1)
    header = await SaveService(uow.session).capture(
        session_id=session.id,
        world_id=session.world_id,
        name=body.name,
        player_name=state.player.name,
        turn_number=session.turn_number,
        world_minute=state.world.current_minute,
        time_label=state.time.label,
        location_name=state.location.name if state.location else "",
        excerpt=segments[-1].text[-160:] if segments else "",
        user_id=principal.user_id,
        playthrough_id=play.id,
    )
    await uow.commit()
    return header.as_dict()


@router.get("/playthroughs/{playthrough_id}/saves")
async def list_playthrough_saves(
    playthrough_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> list[dict[str, Any]]:
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    session_id = play.game_session_id or ""
    headers = await SaveService(uow.session).list_for_session(session_id)
    return [item.as_dict() for item in headers if item.session_id == session_id]


async def _owned_save(
    uow: SqlUnitOfWork, save_id: str, playthrough_id: str, user_id: str
) -> SaveSlotORM:
    slot = await uow.session.scalar(
        sa.select(SaveSlotORM).where(
            SaveSlotORM.id == save_id,
            SaveSlotORM.user_id == user_id,
            SaveSlotORM.playthrough_id == playthrough_id,
        )
    )
    if slot is None:
        raise HTTPException(status_code=404, detail="save not found")
    return slot


@router.post("/playthroughs/{playthrough_id}/saves/{save_id}/load")
async def load_playthrough_save(
    playthrough_id: str,
    save_id: str,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    await _owned_save(uow, save_id, play.id, principal.user_id)
    restored = await SaveService(uow.session).restore(save_id)
    if restored is None:
        raise HTTPException(status_code=404, detail="save not found")
    play.status = "active"
    play.ending_key = None
    play.ending_title = None
    play.completed_at = None
    play.updated_at = datetime.now(UTC)
    await uow.commit()
    return restored.as_dict()


@router.delete("/playthroughs/{playthrough_id}/saves/{save_id}")
async def delete_playthrough_save(
    playthrough_id: str,
    save_id: str,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, bool]:
    await set_tenant_context(uow.session, principal.user_id)
    play = await _owned_playthrough(uow, playthrough_id, principal.user_id)
    await _owned_save(uow, save_id, play.id, principal.user_id)
    await SaveService(uow.session).delete(save_id)
    await uow.commit()
    return {"deleted": True}

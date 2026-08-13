"""Public, searchable release catalog and player reporting API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.dialects import postgresql

from apps.api.deps import settings_dep, uow_dep
from apps.api.security import Principal, require_csrf, token_hash
from apps.api.tenancy import set_tenant_context
from database.models.platform import ContentReleaseORM, PlaythroughORM, ProjectORM, ReportORM
from database.repositories.sql import SqlUnitOfWork
from engine.core.config import Settings
from engine.core.ids import new_id

router = APIRouter(tags=["v1-catalog"])


def _release_view(release: ContentReleaseORM, project: ProjectORM) -> dict[str, Any]:
    manifest = (release.artifact or {}).get("manifest", {})
    content = (release.artifact or {}).get("content", {})
    entry: dict[str, Any] = next(
        (
            item
            for item in content.get("scenarios", [])
            if item.get("key") == manifest.get("entry_scenario")
        ),
        {},
    )
    cover: dict[str, Any] = next(
        (item for item in manifest.get("assets", []) if item.get("kind") == "cover"), {}
    )
    return {
        "id": release.id,
        "project_id": project.id,
        "slug": project.slug,
        "title": release.title,
        "summary": release.summary,
        "version": release.version,
        "locale": release.locale,
        "rating": release.rating,
        "tags": release.tags,
        "theme": manifest.get("theme", {}),
        "player_fields": manifest.get("player_fields", []),
        "capabilities": manifest.get("capabilities", []),
        "cover_url": f"/media/{cover.get('path')}" if cover.get("path") else None,
        "premise": entry.get("premise", ""),
        "player_constraints": (entry.get("player_template") or {}).get("constraints", {}),
        "content_counts": {
            "locations": len(content.get("locations", [])),
            "characters": len(content.get("characters", [])),
            "plot_threads": len(content.get("plot_threads", [])),
            "quests": len(content.get("quests", [])),
        },
        "published_at": release.published_at,
    }


@router.get("/catalog/releases")
async def catalog(
    q: str = "",
    locale: str | None = None,
    rating: str | None = None,
    tag: str | None = Query(default=None, max_length=40),
    sort: Literal["updated", "popular", "newest"] = "updated",
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    dialect_name = uow.session.get_bind().dialect.name
    sqlite_tags = (
        sa.func.json_each(ContentReleaseORM.tags).table_valued("key", "value").alias("catalog_tag")
        if dialect_name == "sqlite"
        else None
    )
    popularity = (
        sa.select(
            PlaythroughORM.release_id,
            sa.func.count(PlaythroughORM.id).label("play_count"),
        )
        .group_by(PlaythroughORM.release_id)
        .subquery()
    )
    stmt = (
        sa.select(
            ContentReleaseORM,
            ProjectORM,
            sa.func.coalesce(popularity.c.play_count, 0).label("play_count"),
        )
        .join(ProjectORM, ProjectORM.id == ContentReleaseORM.project_id)
        .outerjoin(popularity, popularity.c.release_id == ContentReleaseORM.id)
        .where(
            ContentReleaseORM.visibility == "public",
            ContentReleaseORM.moderation_status == "approved",
            ContentReleaseORM.withdrawn_at.is_(None),
        )
    )
    if not settings.adult_catalog_enabled:
        stmt = stmt.where(ContentReleaseORM.rating != "18+")
    if q.strip():
        needle = f"%{q.strip()}%"
        tag_search = (
            sa.exists(
                sa.select(1).select_from(sqlite_tags).where(sqlite_tags.c.value.ilike(needle))
            )
            if sqlite_tags is not None
            else sa.cast(ContentReleaseORM.tags, sa.String).ilike(needle)
        )
        stmt = stmt.where(
            sa.or_(
                ContentReleaseORM.title.ilike(needle),
                ContentReleaseORM.summary.ilike(needle),
                tag_search,
            )
        )
    if locale:
        stmt = stmt.where(ContentReleaseORM.locale == locale)
    if rating:
        stmt = stmt.where(ContentReleaseORM.rating == rating)
    if tag:
        tag_filter = (
            sa.exists(sa.select(1).select_from(sqlite_tags).where(sqlite_tags.c.value == tag))
            if sqlite_tags is not None
            else sa.cast(ContentReleaseORM.tags, postgresql.JSONB).contains([tag])
        )
        stmt = stmt.where(tag_filter)
    total = await uow.session.scalar(sa.select(sa.func.count()).select_from(stmt.subquery()))
    order = (
        (sa.func.coalesce(popularity.c.play_count, 0).desc(), ContentReleaseORM.published_at.desc())
        if sort == "popular"
        else (ContentReleaseORM.created_at.desc(),)
        if sort == "newest"
        else (ProjectORM.updated_at.desc(), ContentReleaseORM.published_at.desc())
    )
    rows = (await uow.session.execute(stmt.order_by(*order).offset(offset).limit(limit))).all()
    items = []
    for release, project, play_count in rows:
        item = _release_view(release, project)
        item["play_count"] = int(play_count)
        items.append(item)
    return {"items": items, "total": total or 0, "limit": limit, "offset": offset}


@router.get("/catalog/releases/{release_id}")
async def release_detail(
    release_id: str,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    row = (
        await uow.session.execute(
            sa.select(ContentReleaseORM, ProjectORM)
            .join(ProjectORM, ProjectORM.id == ContentReleaseORM.project_id)
            .where(ContentReleaseORM.id == release_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="release not found")
    release, project = row
    if (
        release.visibility != "public"
        or release.moderation_status != "approved"
        or release.withdrawn_at
    ):
        raise HTTPException(status_code=404, detail="release not found")
    if release.rating == "18+" and not settings.adult_catalog_enabled:
        raise HTTPException(status_code=404, detail="release not found")
    return _release_view(release, project)


@router.get("/catalog/shared/{share_token}")
async def shared_release_detail(
    share_token: str,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    digest = token_hash(share_token, settings.auth_pepper)
    row = (
        await uow.session.execute(
            sa.select(ContentReleaseORM, ProjectORM)
            .join(ProjectORM, ProjectORM.id == ContentReleaseORM.project_id)
            .where(
                ContentReleaseORM.share_token_hash == digest,
                ContentReleaseORM.visibility == "unlisted",
                ContentReleaseORM.moderation_status == "approved",
                ContentReleaseORM.withdrawn_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="shared release not found")
    return _release_view(row[0], row[1])


class ReportCreate(BaseModel):
    category: str = Field(min_length=2, max_length=60)
    details: str = Field(min_length=3, max_length=4000)


@router.post("/catalog/releases/{release_id}/reports", status_code=201)
async def report_release(
    release_id: str,
    body: ReportCreate,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, str]:
    await set_tenant_context(uow.session, principal.user_id)
    release = await uow.session.get(ContentReleaseORM, release_id)
    if (
        release is None
        or release.visibility != "public"
        or release.moderation_status != "approved"
        or release.withdrawn_at is not None
    ):
        raise HTTPException(status_code=404, detail="release not found")
    report = ReportORM(
        id=new_id(),
        reporter_id=principal.user_id,
        release_id=release.id,
        category=body.category,
        details=body.details,
        status="open",
    )
    uow.session.add(report)
    await uow.commit()
    return {"id": report.id, "status": report.status}

"""Owner-checked or public immutable media delivery."""

from __future__ import annotations

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from apps.api.deps import settings_dep, uow_dep
from apps.api.object_store import object_store
from apps.api.security import Principal, optional_principal
from apps.api.tenancy import set_tenant_context
from database.models.platform import AssetORM, ContentReleaseORM
from database.repositories.sql import SqlUnitOfWork
from engine.core.config import Settings

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/{object_key:path}")
async def get_media(
    object_key: str,
    principal: Annotated[Principal | None, Depends(optional_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> Response:
    if principal is not None:
        await set_tenant_context(uow.session, principal.user_id)
    asset = await uow.session.scalar(
        sa.select(AssetORM).where(
            sa.or_(
                AssetORM.object_key == object_key,
                AssetORM.thumbnail_object_key == object_key,
            ),
            AssetORM.status == "ready",
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="media not found")
    allowed = principal is not None and principal.user_id == asset.owner_id
    is_public_release_asset = False
    if not allowed:
        releases = (
            await uow.session.execute(
                sa.select(ContentReleaseORM.artifact).where(
                    ContentReleaseORM.project_id == asset.project_id,
                    ContentReleaseORM.visibility == "public",
                    ContentReleaseORM.moderation_status == "approved",
                    ContentReleaseORM.withdrawn_at.is_(None),
                )
            )
        ).scalars().all()
        is_public_release_asset = any(
            asset.object_key in {
                str(item.get("path"))
                for item in (artifact.get("manifest", {}).get("assets", []) or [])
            }
            for artifact in releases
        )
        allowed = is_public_release_asset
    if not allowed:
        raise HTTPException(status_code=404, detail="media not found")
    try:
        payload = await object_store(settings).get(object_key)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="media not found") from exc
    return Response(
        payload,
        media_type="image/webp" if object_key == asset.thumbnail_object_key else asset.content_type,
        headers={
            "Cache-Control": (
                "public, max-age=31536000, immutable"
                if is_public_release_asset
                else "private, no-store"
            )
        },
    )

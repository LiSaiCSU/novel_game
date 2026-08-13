"""Creator image ingestion, sanitization, storage and thumbnail scheduling."""

from __future__ import annotations

import hashlib
import io
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from apps.api.creator_access import owned_project
from apps.api.deps import settings_dep, uow_dep
from apps.api.object_store import object_store
from apps.api.security import Principal, require_csrf, verified_principal
from apps.api.tenancy import set_tenant_context
from apps.api.upload_scan import UploadMalwareDetected, UploadScanUnavailable, scan_upload
from apps.jobs import enqueue_job
from database.models.platform import AssetORM
from database.repositories.sql import SqlUnitOfWork
from engine.core.config import Settings
from engine.core.ids import new_id

router = APIRouter(prefix="/creator", tags=["v1-creator-assets"])

_ASSET_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_ASSET_KINDS = {"cover", "avatar", "background"}


@router.post("/projects/{project_id}/assets", status_code=201)
async def upload_asset(
    project_id: str,
    key: Annotated[str, Form(pattern=r"^[a-z][a-z0-9_]{1,79}$")],
    kind: Annotated[str, Form()],
    alt_text: Annotated[str, Form(max_length=300)],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    await owned_project(uow, project_id, principal.user_id)
    collision = await uow.session.scalar(
        sa.select(AssetORM.id).where(AssetORM.project_id == project_id, AssetORM.logical_key == key)
    )
    if collision:
        raise HTTPException(status_code=409, detail="asset key already exists")
    if kind not in _ASSET_KINDS or file.content_type not in _ASSET_MIME:
        raise HTTPException(
            status_code=415,
            detail="only cover, avatar and background JPEG/PNG/WebP images are supported",
        )
    raw = await file.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="asset exceeds the 8 MB limit")
    try:
        await scan_upload(settings, raw)
    except UploadMalwareDetected as exc:
        raise HTTPException(
            status_code=422, detail="uploaded asset failed malware screening"
        ) from exc
    except UploadScanUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="upload screening is temporarily unavailable"
        ) from exc
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            width, height = source.size
            if width < 64 or height < 64 or width > 6000 or height > 6000:
                raise HTTPException(
                    status_code=422, detail="image dimensions must be between 64 and 6000 pixels"
                )
            cleaned = source.convert("RGB")
            output = io.BytesIO()
            output_format = (
                "JPEG"
                if file.content_type == "image/jpeg"
                else file.content_type.split("/")[1].upper()
            )
            cleaned.save(output, format=output_format, quality=90, optimize=True)
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=422, detail="image could not be decoded") from exc
    payload = output.getvalue()
    checksum = hashlib.sha256(payload).hexdigest()
    extension = _ASSET_MIME[file.content_type]
    object_key = f"{principal.user_id}/{project_id}/{checksum}.{extension}"
    await object_store(settings).put(object_key, payload, file.content_type)
    asset = AssetORM(
        id=new_id(),
        owner_id=principal.user_id,
        project_id=project_id,
        kind=kind,
        logical_key=key,
        object_key=object_key,
        content_type=file.content_type,
        byte_size=len(payload),
        checksum=checksum,
        width=width,
        height=height,
        alt_text=alt_text,
        status="ready",
    )
    uow.session.add(asset)
    await uow.commit()
    queued = await enqueue_job(
        settings,
        "generate_asset_thumbnail",
        {"asset_id": asset.id, "owner_id": principal.user_id},
    )
    if not queued:
        from apps.worker.tasks import generate_asset_thumbnail

        await generate_asset_thumbnail(settings, asset.id, principal.user_id)
        await uow.session.refresh(asset)
    return {
        "id": asset.id,
        "key": key,
        "kind": kind,
        "path": object_key,
        "url": f"/media/{object_key}",
        "width": width,
        "height": height,
        "byte_size": len(payload),
        "alt": alt_text,
        "thumbnail_url": (
            f"/media/{asset.thumbnail_object_key}" if asset.thumbnail_object_key else None
        ),
    }


@router.get("/projects/{project_id}/assets")
async def list_assets(
    project_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> list[dict[str, Any]]:
    await set_tenant_context(uow.session, principal.user_id)
    await owned_project(uow, project_id, principal.user_id)
    rows = (
        (
            await uow.session.execute(
                sa.select(AssetORM)
                .where(AssetORM.project_id == project_id, AssetORM.owner_id == principal.user_id)
                .order_by(AssetORM.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "key": row.logical_key,
            "kind": row.kind,
            "path": row.object_key,
            "url": f"/media/{row.object_key}",
            "width": row.width,
            "height": row.height,
            "byte_size": row.byte_size,
            "thumbnail_url": (
                f"/media/{row.thumbnail_object_key}" if row.thumbnail_object_key else None
            ),
            "thumbnail_width": row.thumbnail_width,
            "thumbnail_height": row.thumbnail_height,
            "alt": row.alt_text,
            "status": row.status,
        }
        for row in rows
    ]

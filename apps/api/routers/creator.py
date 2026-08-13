"""Creator projects, optimistic revisions and immutable release workflow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import sqlalchemy as sa
import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from apps.api.content_import import IMPORT_MAX_BYTES, import_document
from apps.api.creator_access import owned_project
from apps.api.deps import settings_dep, uow_dep
from apps.api.product_analytics import record_product_event
from apps.api.security import (
    Principal,
    opaque_token,
    require_csrf,
    token_hash,
    verified_principal,
)
from apps.api.tenancy import set_tenant_context
from apps.api.upload_scan import UploadMalwareDetected, UploadScanUnavailable, scan_upload
from apps.authoring.templates import build_project_template, list_project_templates
from apps.authoring.testing import run_author_tests
from apps.jobs import enqueue_job
from database.models.platform import (
    AssetORM,
    AuditLogORM,
    ContentReleaseORM,
    ModerationCaseORM,
    ProjectORM,
    ProjectRevisionORM,
    UserRoleORM,
)
from database.repositories.sql import SqlUnitOfWork
from engine.contentpack.compiler import compile_package, validate_package_graph
from engine.contentpack.schema_v2 import ContentPackageV2
from engine.core.config import Settings
from engine.core.errors import ContentValidationError
from engine.core.ids import new_id

router = APIRouter(prefix="/creator", tags=["v1-creator"])


class ProjectCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=1000)
    locale: str = Field(default="zh-CN", max_length=20)
    rating: Literal["all", "13+", "16+", "18+"] = "16+"
    document: dict[str, Any] | None = None
    template_key: str = Field(default="blank", max_length=40)


class RevisionUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    document: dict[str, Any]


class PublishRequest(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$", max_length=40)
    visibility: Literal["private", "unlisted", "public"] = "private"


class ShareTokenWrite(BaseModel):
    rotate: bool = True


class AppealRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


def _project_view(row: ProjectORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "slug": row.slug,
        "title": row.title,
        "summary": row.summary,
        "locale": row.locale,
        "rating": row.rating,
        "status": row.status,
        "revision": row.current_revision,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/content-pack-schema")
async def content_pack_schema() -> dict[str, Any]:
    """Machine-readable author contract used by editors and external tooling."""
    return ContentPackageV2.model_json_schema()


@router.get("/templates")
async def project_templates() -> list[dict[str, Any]]:
    """Return compiler-verified starters shared with the author CLI."""
    return list_project_templates()


@router.post("/projects", status_code=201)
async def create_project(
    body: ProjectCreate,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    collision = await uow.session.scalar(
        sa.select(ProjectORM.id).where(
            ProjectORM.owner_id == principal.user_id, ProjectORM.slug == body.slug
        )
    )
    if collision:
        raise HTTPException(status_code=409, detail="project slug already exists")
    try:
        package = (
            ContentPackageV2.model_validate(body.document)
            if body.document is not None
            else build_project_template(
                body.template_key,
                title=body.title,
                slug=body.slug,
                summary=body.summary,
                locale=body.locale,
                rating=body.rating,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if package.manifest.slug != body.slug:
        raise HTTPException(status_code=422, detail="project slug must match manifest slug")
    if package.manifest.trusted_rule_plugin:
        raise HTTPException(
            status_code=422, detail="web projects cannot install Python rule plugins"
        )
    project = ProjectORM(
        id=new_id(),
        owner_id=principal.user_id,
        slug=body.slug,
        title=package.manifest.title,
        summary=package.manifest.summary,
        locale=package.manifest.locale,
        rating=package.manifest.rating,
        current_revision=1,
    )
    revision = ProjectRevisionORM(
        id=new_id(),
        project_id=project.id,
        author_id=principal.user_id,
        revision=1,
        document=package.model_dump(mode="json"),
        diagnostics=[],
    )
    uow.session.add_all([project, revision])
    has_creator = await uow.session.scalar(
        sa.select(UserRoleORM.id).where(
            UserRoleORM.user_id == principal.user_id, UserRoleORM.role == "creator"
        )
    )
    if not has_creator:
        uow.session.add(UserRoleORM(id=new_id(), user_id=principal.user_id, role="creator"))
    await record_product_event(
        uow,
        principal,
        "project_created",
        project_id=project.id,
        dedupe_key=project.id,
        properties={"template_key": body.template_key},
    )
    await uow.commit()
    return _project_view(project)


@router.post("/import", status_code=201)
async def import_project(
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    raw = await file.read(IMPORT_MAX_BYTES + 1)
    if len(raw) > IMPORT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="content import exceeds the 10 MB limit")
    try:
        await scan_upload(settings, raw)
    except UploadMalwareDetected as exc:
        raise HTTPException(
            status_code=422, detail="uploaded content failed malware screening"
        ) from exc
    except UploadScanUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="upload screening is temporarily unavailable"
        ) from exc
    document = import_document(raw, file.filename or "package.yaml")
    try:
        package = ContentPackageV2.model_validate(document)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await create_project(
        ProjectCreate(
            slug=package.manifest.slug,
            title=package.manifest.title,
            summary=package.manifest.summary,
            locale=package.manifest.locale,
            rating=package.manifest.rating,
            document=package.model_dump(mode="json"),
        ),
        principal,
        uow,
    )


@router.get("/projects")
async def list_projects(
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> list[dict[str, Any]]:
    await set_tenant_context(uow.session, principal.user_id)
    rows = (
        (
            await uow.session.execute(
                sa.select(ProjectORM)
                .where(ProjectORM.owner_id == principal.user_id)
                .order_by(ProjectORM.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_project_view(row) for row in rows]


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    project = await owned_project(uow, project_id, principal.user_id)
    revision = await uow.session.scalar(
        sa.select(ProjectRevisionORM).where(
            ProjectRevisionORM.project_id == project.id,
            ProjectRevisionORM.revision == project.current_revision,
        )
    )
    return {**_project_view(project), "document": revision.document if revision else {}}


@router.get("/projects/{project_id}/revisions")
async def list_revisions(
    project_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> list[dict[str, Any]]:
    await set_tenant_context(uow.session, principal.user_id)
    project = await owned_project(uow, project_id, principal.user_id)
    rows = (
        (
            await uow.session.execute(
                sa.select(ProjectRevisionORM)
                .where(ProjectRevisionORM.project_id == project.id)
                .order_by(ProjectRevisionORM.revision.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "revision": row.revision,
            "created_at": row.created_at,
            "diagnostics": row.diagnostics,
            "document": row.document,
        }
        for row in rows
    ]


@router.get("/projects/{project_id}/releases")
async def list_releases(
    project_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> list[dict[str, Any]]:
    await set_tenant_context(uow.session, principal.user_id)
    project = await owned_project(uow, project_id, principal.user_id)
    rows = (
        (
            await uow.session.execute(
                sa.select(ContentReleaseORM)
                .where(ContentReleaseORM.project_id == project.id)
                .order_by(ContentReleaseORM.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "version": row.version,
            "checksum": row.checksum,
            "visibility": row.visibility,
            "status": row.moderation_status,
            "created_at": row.created_at,
            "withdrawn_at": row.withdrawn_at,
        }
        for row in rows
    ]


@router.post("/projects/{project_id}/share-token")
async def rotate_project_share_token(
    project_id: str,
    _body: ShareTokenWrite,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, str]:
    await set_tenant_context(uow.session, principal.user_id)
    project = await owned_project(uow, project_id, principal.user_id)
    token = opaque_token()
    project.share_token_hash = token_hash(token, settings.auth_pepper)
    await uow.commit()
    return {"share_token": token}


@router.get("/shared/{share_token}")
async def shared_project_preview(
    share_token: str,
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    digest = token_hash(share_token, settings.auth_pepper)
    project = await uow.session.scalar(
        sa.select(ProjectORM).where(ProjectORM.share_token_hash == digest)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="shared project not found")
    revision = await uow.session.scalar(
        sa.select(ProjectRevisionORM).where(
            ProjectRevisionORM.project_id == project.id,
            ProjectRevisionORM.revision == project.current_revision,
        )
    )
    if revision is None:
        raise HTTPException(status_code=404, detail="shared project not found")
    package = ContentPackageV2.model_validate(revision.document)
    return {
        "title": package.manifest.title,
        "summary": package.manifest.summary,
        "rating": package.manifest.rating,
        "locale": package.manifest.locale,
        "revision": project.current_revision,
        "diagnostics": [
            {"level": "error", "message": item} for item in validate_package_graph(package)
        ],
        "content_counts": {
            "locations": len(package.content.locations),
            "characters": len(package.content.characters),
            "plot_threads": len(package.content.plot_threads),
            "quests": len(package.content.quests),
        },
    }


@router.put("/projects/{project_id}/document")
async def update_document(
    project_id: str,
    body: RevisionUpdate,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    project = await owned_project(uow, project_id, principal.user_id)
    if project.current_revision != body.expected_revision:
        current = await uow.session.scalar(
            sa.select(ProjectRevisionORM.document).where(
                ProjectRevisionORM.project_id == project.id,
                ProjectRevisionORM.revision == project.current_revision,
            )
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "revision_conflict",
                "revision": project.current_revision,
                "document": current,
            },
        )
    try:
        package = ContentPackageV2.model_validate(body.document)
        diagnostics = [
            {"level": "error", "message": item} for item in validate_package_graph(package)
        ]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if package.manifest.slug != project.slug:
        raise HTTPException(status_code=422, detail="manifest slug is immutable for a project")
    if package.manifest.trusted_rule_plugin:
        raise HTTPException(
            status_code=422, detail="web projects cannot install Python rule plugins"
        )
    project.current_revision += 1
    project.title = package.manifest.title
    project.summary = package.manifest.summary
    project.locale = package.manifest.locale
    project.rating = package.manifest.rating
    revision = ProjectRevisionORM(
        id=new_id(),
        project_id=project.id,
        author_id=principal.user_id,
        revision=project.current_revision,
        document=package.model_dump(mode="json"),
        diagnostics=diagnostics,
    )
    uow.session.add(revision)
    await uow.commit()
    return {"revision": project.current_revision, "diagnostics": diagnostics}


@router.post("/projects/{project_id}/validate")
async def validate_project(
    project_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    project = await owned_project(uow, project_id, principal.user_id)
    document = await uow.session.scalar(
        sa.select(ProjectRevisionORM.document).where(
            ProjectRevisionORM.project_id == project.id,
            ProjectRevisionORM.revision == project.current_revision,
        )
    )
    if document is None:
        raise HTTPException(status_code=409, detail="project has no revision")
    try:
        package = ContentPackageV2.model_validate(document)
        release = compile_package(package)
    except (ValueError, ContentValidationError) as exc:
        problems = getattr(exc, "context", {}).get("problems") or [str(exc)]
        await record_product_event(
            uow,
            principal,
            "project_validated",
            project_id=project.id,
            properties={"valid": False, "error_count": len(problems)},
        )
        await uow.commit()
        return {
            "valid": False,
            "diagnostics": [{"level": "error", "message": p} for p in problems],
            "author_tests": None,
        }
    test_suite = await run_author_tests(package)
    test_diagnostics = [
        {
            "level": "error",
            "message": f"玩法测试 {case.name!r} 未通过",
        }
        for case in test_suite.results
        if not case.passed
    ]
    await record_product_event(
        uow,
        principal,
        "project_validated",
        project_id=project.id,
        properties={
            "valid": test_suite.passed,
            "error_count": len(test_diagnostics),
            "author_test_count": test_suite.declared_tests,
        },
    )
    await uow.commit()
    return {
        "valid": test_suite.passed,
        "checksum": release.checksum,
        "diagnostics": test_diagnostics,
        "author_tests": test_suite.model_dump(mode="json"),
    }


@router.post("/projects/{project_id}/releases", status_code=201)
async def create_release(
    project_id: str,
    body: PublishRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    await set_tenant_context(uow.session, principal.user_id)
    project = await owned_project(uow, project_id, principal.user_id)
    revision = await uow.session.scalar(
        sa.select(ProjectRevisionORM).where(
            ProjectRevisionORM.project_id == project.id,
            ProjectRevisionORM.revision == project.current_revision,
        )
    )
    if revision is None:
        raise HTTPException(status_code=409, detail="project has no revision")
    try:
        package = ContentPackageV2.model_validate(revision.document)
        compiled = compile_package(package)
    except (ValueError, ContentValidationError) as exc:
        detail = getattr(exc, "context", {}).get("problems") or str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc
    if compiled.manifest.trusted_rule_plugin:
        raise HTTPException(
            status_code=422, detail="uploaded projects cannot use Python rule plugins"
        )
    test_suite = await run_author_tests(package)
    if not test_suite.passed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "AUTHOR_TESTS_FAILED",
                "message": "玩法测试未通过，不能创建不可变版本",
                "suite": test_suite.model_dump(mode="json"),
            },
        )
    if body.visibility == "public" and test_suite.declared_tests == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "AUTHOR_TESTS_REQUIRED",
                "message": "公开发布至少需要一条创作者声明的玩法测试",
            },
        )
    if compiled.manifest.rating == "18+" and not settings.adult_catalog_enabled:
        raise HTTPException(status_code=403, detail="18+ catalog publishing is disabled")
    asset_paths = {item.path for item in compiled.manifest.assets}
    if asset_paths:
        stored_paths = set(
            (
                await uow.session.execute(
                    sa.select(AssetORM.object_key).where(
                        AssetORM.project_id == project.id,
                        AssetORM.owner_id == principal.user_id,
                        AssetORM.status == "ready",
                    )
                )
            )
            .scalars()
            .all()
        )
        missing = sorted(asset_paths - stored_paths)
        if missing:
            raise HTTPException(
                status_code=422, detail=f"release assets are unavailable: {', '.join(missing)}"
            )
    visibility = body.visibility
    moderation_status = "pending" if visibility == "public" else "approved"
    release = ContentReleaseORM(
        id=new_id(),
        project_id=project.id,
        revision_id=revision.id,
        owner_id=principal.user_id,
        version=body.version,
        checksum=compiled.checksum,
        title=compiled.manifest.title,
        summary=compiled.manifest.summary,
        locale=compiled.manifest.locale,
        rating=compiled.manifest.rating,
        tags=compiled.manifest.tags,
        visibility=visibility,
        moderation_status=moderation_status,
        artifact=compiled.model_dump(mode="json"),
        published_at=datetime.now(UTC) if visibility != "public" else None,
    )
    share_token = opaque_token() if visibility == "unlisted" else None
    if share_token:
        release.share_token_hash = token_hash(share_token, settings.auth_pepper)
    uow.session.add(release)
    if visibility == "public":
        uow.session.add(
            ModerationCaseORM(
                id=new_id(),
                release_id=release.id,
                submitter_id=principal.user_id,
                status="pending",
                decision_reason="",
                evidence=[],
            )
        )
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="release.created",
            target_type="content_release",
            target_id=release.id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={
                "project_id": project.id,
                "version": body.version,
                "visibility": visibility,
                "checksum": release.checksum,
            },
        )
    )
    await record_product_event(
        uow,
        principal,
        "release_created",
        project_id=project.id,
        release_id=release.id,
        dedupe_key=release.id,
        properties={"visibility": visibility},
    )
    await uow.commit()
    if visibility == "public":
        queued = await enqueue_job(
            settings,
            "moderation_scan",
            {"release_id": release.id, "owner_id": principal.user_id},
        )
        if not queued:
            from apps.worker.tasks import scan_release

            await scan_release(settings, release.id, principal.user_id)
    return {
        "id": release.id,
        "checksum": release.checksum,
        "status": moderation_status,
        # An unlisted token is intentionally returned once and never stored in plaintext.
        "share_token": share_token,
    }


@router.get("/projects/{project_id}/export")
async def export_project(
    project_id: str,
    principal: Annotated[Principal, Depends(verified_principal)],
    uow: SqlUnitOfWork = Depends(uow_dep),
    format: Literal["json", "yaml"] = "json",
) -> Response:
    await set_tenant_context(uow.session, principal.user_id)
    project = await owned_project(uow, project_id, principal.user_id)
    document = await uow.session.scalar(
        sa.select(ProjectRevisionORM.document).where(
            ProjectRevisionORM.project_id == project.id,
            ProjectRevisionORM.revision == project.current_revision,
        )
    )
    if document is None:
        raise HTTPException(status_code=409, detail="project has no revision")
    if format == "yaml":
        payload = yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
        media_type = "application/yaml"
        extension = "yaml"
    else:
        payload = json.dumps(document, ensure_ascii=False, indent=2)
        media_type = "application/json"
        extension = "json"
    return Response(
        payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{project.slug}.{extension}"'},
    )


@router.post("/projects/{project_id}/releases/{release_id}/appeal", status_code=202)
async def appeal_release(
    project_id: str,
    release_id: str,
    body: AppealRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_csrf)],
    uow: SqlUnitOfWork = Depends(uow_dep),
) -> dict[str, str]:
    await set_tenant_context(uow.session, principal.user_id)
    await owned_project(uow, project_id, principal.user_id)
    release = await uow.session.scalar(
        sa.select(ContentReleaseORM).where(
            ContentReleaseORM.id == release_id,
            ContentReleaseORM.project_id == project_id,
            ContentReleaseORM.owner_id == principal.user_id,
        )
    )
    if release is None or release.moderation_status not in {"rejected", "withdrawn"}:
        raise HTTPException(status_code=409, detail="release is not eligible for appeal")
    existing = await uow.session.scalar(
        sa.select(ModerationCaseORM.id).where(
            ModerationCaseORM.release_id == release.id,
            ModerationCaseORM.status == "pending",
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="an appeal is already pending")
    case = ModerationCaseORM(
        id=new_id(),
        release_id=release.id,
        submitter_id=principal.user_id,
        status="pending",
        decision_reason="",
        evidence=[{"kind": "appeal", "reason": body.reason}],
    )
    release.moderation_status = "pending"
    uow.session.add(case)
    uow.session.add(
        AuditLogORM(
            id=new_id(),
            actor_id=principal.user_id,
            action="moderation.appealed",
            target_type="content_release",
            target_id=release.id,
            request_id=str(getattr(request.state, "request_id", "")),
            details={"case_id": case.id, "reason": body.reason},
        )
    )
    await uow.commit()
    return {"status": "pending", "case_id": case.id}

"""Idempotent installation of bundled official projects and releases."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

import database.session as db_session
from database.models.platform import (
    ContentReleaseORM,
    ProjectORM,
    ProjectRevisionORM,
    UserORM,
    UserRoleORM,
)
from engine.contentpack.compiler import compile_package
from engine.contentpack.legacy_v2 import project_v1_as_v2
from engine.contentpack.pack import load_content_pack
from engine.core.config import Settings
from engine.core.ids import new_id

SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"


async def ensure_official_releases(settings: Settings) -> None:
    maker = db_session.get_sessionmaker(settings)
    async with maker() as session:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            await session.execute(
                sa.text("SELECT set_config('app.current_user_id', :user_id, true)"),
                {"user_id": SYSTEM_USER_ID},
            )
        system = await session.get(UserORM, SYSTEM_USER_ID)
        if system is None:
            system = UserORM(
                id=SYSTEM_USER_ID,
                email="official@local.invalid",
                password_hash="!system-account-no-login!",
                display_name="官方内容团队",
                status="system",
                email_verified_at=None,
            )
            session.add(system)
            session.add(UserRoleORM(id=new_id(), user_id=system.id, role="admin"))
        await _ensure_pack(session, settings, "cultivation_v1", "seven-day-blood-pact", ["修仙", "悬疑"])
        campus_dir = settings.content_path / "campus_romance_v1"
        if campus_dir.is_dir():
            await _ensure_pack(session, settings, "campus_romance_v1", "unfinished-spring-messages", ["校园", "恋爱", "女性向"])
        await session.commit()


async def _ensure_pack(session, settings: Settings, pack_key: str, slug: str, tags: list[str]) -> None:
    pack = load_content_pack(settings.content_path, pack_key)
    package = project_v1_as_v2(pack, slug=slug, rating="16+", tags=tags)
    compiled = compile_package(package)
    project = await session.scalar(
        sa.select(ProjectORM).where(
            ProjectORM.owner_id == SYSTEM_USER_ID, ProjectORM.slug == slug
        )
    )
    if project is None:
        project = ProjectORM(
            id=new_id(), owner_id=SYSTEM_USER_ID, slug=slug, title=package.manifest.title,
            summary=package.manifest.summary, locale=package.manifest.locale,
            rating=package.manifest.rating, status="published", current_revision=0,
            project_metadata={"official": True},
        )
        session.add(project)
    existing = await session.scalar(
        sa.select(ContentReleaseORM).where(
            ContentReleaseORM.project_id == project.id,
            ContentReleaseORM.checksum == compiled.checksum,
        )
    )
    if existing is not None:
        return
    version_collision = await session.scalar(
        sa.select(ContentReleaseORM.id).where(
            ContentReleaseORM.project_id == project.id,
            ContentReleaseORM.version == package.manifest.version,
        )
    )
    if version_collision:
        raise RuntimeError(
            f"official pack {pack_key!r} changed without a version bump ({package.manifest.version})"
        )
    project.current_revision += 1
    project.title = package.manifest.title
    project.summary = package.manifest.summary
    project.locale = package.manifest.locale
    project.rating = package.manifest.rating
    revision = ProjectRevisionORM(
        id=new_id(), project_id=project.id, author_id=SYSTEM_USER_ID,
        revision=project.current_revision,
        document=package.model_dump(mode="json"), diagnostics=[]
    )
    # Keep this ordering explicit. PostgreSQL enforces the release -> revision
    # foreign key during flush; relying on a later add_all() left ordering to
    # the ORM and failed on a truly empty production-shaped database.
    session.add(revision)
    await session.flush()
    release = ContentReleaseORM(
        id=new_id(), project_id=project.id, revision_id=revision.id, owner_id=SYSTEM_USER_ID,
        version=package.manifest.version, checksum=compiled.checksum, title=package.manifest.title,
        summary=package.manifest.summary, locale=package.manifest.locale, rating=package.manifest.rating,
        tags=package.manifest.tags, visibility="public", moderation_status="approved",
        artifact=compiled.model_dump(mode="json"),
        published_at=datetime.now(UTC),
    )
    await session.execute(
        sa.update(ContentReleaseORM)
        .where(
            ContentReleaseORM.project_id == project.id,
            ContentReleaseORM.visibility == "public",
            ContentReleaseORM.withdrawn_at.is_(None),
        )
        .values(withdrawn_at=sa.func.now())
    )
    session.add(release)
